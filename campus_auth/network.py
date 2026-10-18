"""网络层：发现可用于认证的物理网卡，并让出站连接绑定到指定网卡。

只做三件事：
1. 枚举带 IPv4 的物理网卡（排除回环、链路本地、Tailscale/隧道虚拟卡）；
2. 让一个 socket 绑定到指定网卡的源地址与出站接口；
3. 通过 HTTPS 握手 + 证书校验判断外网是否可达。

网卡枚举调用 Windows 的 GetAdaptersAddresses（iphlpapi）。在纯标准库下，
这是枚举网卡地址列表的唯一可靠途径；这里按微软 SDK 的结构体定义读取，
仅声明到 OperStatus 为止的只读前缀。
"""
from __future__ import annotations

import ctypes
import http.client
import ipaddress
import re
import socket
import ssl
import struct
import sys
import urllib.parse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from . import __version__
from .logutil import write_scrubbed_log

# 统一 User-Agent（版本号跟随 campus_auth.__version__，避免多文件各自漂移）
UA = f"campus-auth/{__version__}"

# Windows 上"出站接口"这一 socket 选项的常量。较新的 Python 已内置
# socket.IP_UNICAST_IF，旧版本没有，回退到其标准值 31。
try:
    IP_UNICAST_IF = socket.IP_UNICAST_IF
except AttributeError:  # pragma: no cover - 取决于 Python 版本
    IP_UNICAST_IF = 31


@dataclass(frozen=True)
class NetworkAdapter:
    """一张可以用于认证的物理网卡。"""

    index: int
    name: str
    ipv4: str
    mac: str
    dns: tuple[str, ...]
    kind: str  # "ethernet" | "wifi"

    @property
    def is_ethernet(self) -> bool:
        return self.kind == "ethernet"


# --------------------------------------------------------------------------
# Windows SDK 结构体（只定义读取所需的前缀，命名沿用微软官方字段名）
# --------------------------------------------------------------------------

class _SocketAddress(ctypes.Structure):
    """SOCKET_ADDRESS：一个 sockaddr 指针及其字节长度。"""
    _fields_ = [
        ("lpSockaddr", ctypes.c_void_p),
        ("iSockaddrLength", ctypes.c_int),
    ]


class _UnicastAddress(ctypes.Structure):
    """IP_ADAPTER_UNICAST_ADDRESS_LH 的前缀：联合体 + 下一节点 + 地址。"""
    pass


_UnicastAddress._fields_ = [
    ("Alignment", ctypes.c_uint64),  # Length 与 Flags 的 8 字节联合体
    ("Next", ctypes.POINTER(_UnicastAddress)),
    ("Address", _SocketAddress),
]


class _AdapterAddresses(ctypes.Structure):
    """IP_ADAPTER_ADDRESSES_LH 的前缀，读到 OperStatus 为止。"""
    pass


_AdapterAddresses._fields_ = [
    ("Alignment", ctypes.c_uint64),  # Length 与 IfIndex 的 8 字节联合体
    ("Next", ctypes.POINTER(_AdapterAddresses)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(_UnicastAddress)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(_UnicastAddress)),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", ctypes.c_uint32),
    ("Flags", ctypes.c_uint32),
    ("Mtu", ctypes.c_uint32),
    ("IfType", ctypes.c_uint32),
    ("OperStatus", ctypes.c_uint32),
]


# 只把这些链路类型视作"物理网卡"：以太网(6) 与 802.11 无线(71)。
_ETHERNET_IF_TYPE = 6
_WIFI_IF_TYPE = 71
_IF_OPER_UP = 1

# 不参与认证的地址空间（回环/链路本地/未指定/TUN 假地址段）。
_EXCLUDED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("198.18.0.0/15"),
)


def _read_ipv4(address: _SocketAddress) -> str | None:
    """从 SOCKET_ADDRESS 里解出一个 AF_INET 地址；不是 IPv4 返回 None。"""
    if not address.lpSockaddr or address.iSockaddrLength < 8:
        return None
    raw = ctypes.string_at(address.lpSockaddr, 8)
    family = struct.unpack("=H", raw[:2])[0]
    if family != socket.AF_INET:
        return None
    return socket.inet_ntoa(raw[4:8])


def _walk_ipv4(head) -> Iterator[str]:
    """遍历单链表，逐个 yield 解析出的 IPv4 地址。"""
    node = head
    while node:
        value = _read_ipv4(node.contents.Address)
        if value:
            yield value
        node = node.contents.Next


def _usable(address: str) -> bool:
    try:
        parsed = ipaddress.IPv4Address(address)
    except ValueError:
        return False
    return not any(parsed in network for network in _EXCLUDED_NETWORKS)


def enumerate_interfaces() -> tuple[NetworkAdapter, ...]:
    """返回带可用 IPv4 的物理网卡（以太网/Wi-Fi），过滤虚拟与隧道网卡。"""
    if sys.platform != "win32":
        return ()

    get_addresses = ctypes.WinDLL("iphlpapi").GetAdaptersAddresses
    get_addresses.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.POINTER(_AdapterAddresses), ctypes.POINTER(ctypes.c_uint32),
    ]
    get_addresses.restype = ctypes.c_uint32

    # AF_INET，附带网关/多播跳过标志
    flags = 0x2 | 0x4
    # 网卡较多时首次缓冲区可能不足：Windows 会通过 buffer_size 回传所需大小，
    # 这里最多重试 3 次；ERROR_BUFFER_OVERFLOW = 111。
    buffer_size = ctypes.c_uint32(15000)
    head = None
    for _ in range(3):
        storage = ctypes.create_string_buffer(buffer_size.value)
        head = ctypes.cast(storage, ctypes.POINTER(_AdapterAddresses))
        rc = get_addresses(socket.AF_INET, flags, None, head, ctypes.byref(buffer_size))
        if rc == 0:
            break
        if rc != 111:
            return ()
    else:
        return ()

    found: list[NetworkAdapter] = []
    node = head
    while node:
        info = node.contents
        is_physical = (
            info.OperStatus == _IF_OPER_UP
            and info.IfType in (_ETHERNET_IF_TYPE, _WIFI_IF_TYPE)
            and info.PhysicalAddressLength > 0
        )
        if is_physical:
            mac = "-".join(f"{info.PhysicalAddress[i]:02x}" for i in range(info.PhysicalAddressLength))
            for ipv4 in _walk_ipv4(info.FirstUnicastAddress):
                if not _usable(ipv4):
                    continue
                kind = "wifi" if info.IfType == _WIFI_IF_TYPE else "ethernet"
                found.append(NetworkAdapter(
                    index=info.Alignment >> 32,  # 联合体高 32 位是 IfIndex
                    name=info.FriendlyName or info.Description or "",
                    ipv4=ipv4,
                    mac=mac,
                    dns=tuple(_walk_ipv4(info.FirstDnsServerAddress)),
                    kind=kind,
                ))
                break  # 每张卡只取第一个可用 IPv4
        node = info.Next
    return tuple(found)


def pick_adapter(adapters: Sequence[NetworkAdapter], prefer_ethernet: bool = True) -> NetworkAdapter | None:
    """从若干网卡里选一张：默认优先有线，其次按枚举顺序。"""
    if not adapters:
        return None
    if prefer_ethernet:
        for adapter in adapters:
            if adapter.is_ethernet:
                return adapter
    return adapters[0]


def _pin_socket(sock: socket.socket, adapter: NetworkAdapter) -> None:
    """让 socket 的流量从指定网卡发出：绑定源地址 + 指定出站接口。"""
    sock.bind((adapter.ipv4, 0))
    try:
        sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", adapter.index))
    except OSError:
        pass  # 不支持时退化为仅绑定源地址


class BoundHTTPConnection(http.client.HTTPConnection):
    """把出站连接固定到指定网卡的 HTTPConnection。"""

    def __init__(self, host: str, port: int = 80, *, adapter: NetworkAdapter | None = None,
                 timeout: float = 10):
        self._adapter = adapter
        super().__init__(host, port, timeout=timeout)

    def connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self._adapter is not None:
            _pin_socket(sock, self._adapter)
        sock.settimeout(self.timeout)
        sock.connect((self.host, self.port))
        self.sock = sock


def https_reachable(host: str, *, adapter: NetworkAdapter | None = None,
                    timeout: float = 3.0, port: int = 443) -> bool:
    """通过一次完整 TLS 握手 + 主机名校验判断 https 站点是否可达。"""
    context = ssl.create_default_context()
    conn: BoundHTTPConnection | None = None
    try:
        conn = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
        conn.connect()
        secure = context.wrap_socket(conn.sock, server_hostname=host)
        secure.settimeout(timeout)
        secure.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("ascii"))
        with http.client.HTTPResponse(secure) as response:
            response.begin()
            # HEAD 请求有些站点返回 405 / 重定向，2xx~3xx 都视为可达
            return 200 <= response.status < 400
    except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# 公网探测 IP（DNS 服务器 IP，稳定；用于在校园网 DNS 故障时绕开域名解析）
PUBLIC_PROBE_IPS = ("223.5.5.5", "119.29.29.29", "180.76.76.76", "114.114.114.114")


def internet_ok_by_ip(adapter: NetworkAdapter | None = None, timeout: float = 3.0) -> bool:
    """判断是否已联网（完全不依赖 DNS）。

    优先用 NCSI 检测点的 IP 直连（带 Host 头）并校验正文：真正放行时返回
    「Microsoft Connect Test」，网关劫持时返回认证页 → 判未联网，比只看
    HTTP 是否超时更可靠。NCSI 检测点全不可达时，回退到公网 IP 的劫持特征判断。
    """
    # 1) NCSI 检测点 IP 直连 + 内容校验（劫持页正文不匹配，天然区分）
    for ip in _NCSI_IPS:
        if _ncsi_probe(ip, timeout, use_host_header=True, adapter=adapter):
            return True

    # 2) 回退：公网 IP 的 HTTP 响应是否被网关劫持
    for ip in PUBLIC_PROBE_IPS:
        try:
            conn = BoundHTTPConnection(ip, 80, adapter=adapter, timeout=timeout)
            conn.request("GET", "/", headers={"User-Agent": UA, "Connection": "close"})
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            conn.close()
            # 被网关劫持（含跳转到认证页）→ 未认证
            if "location.href" in body or "eportal" in body.lower():
                return False
            # 正常响应（未被劫持）→ 已联网
            return True
        except (OSError, ValueError, http.client.HTTPException):
            continue
    return False


# 微软 NCSI 检测点（域名解析失败时用 IP 直连 + Host 头绕开坏 DNS）
_NCSI_HOST = "www.msftconnecttest.com"
_NCSI_EXPECT = "Microsoft Connect Test"
_NCSI_IPS = ("13.107.4.50", "13.107.246.40", "204.79.197.200")


def _ncsi_probe(host: str, timeout: float, use_host_header: bool = False,
                adapter: NetworkAdapter | None = None) -> bool:
    """访问一次 NCSI 检测点并校验响应内容。

    走 BoundHTTPConnection 以便多网卡时绑定到配置的网卡（避免走错网卡误判）。
    """
    try:
        conn = BoundHTTPConnection(host, 80, adapter=adapter, timeout=timeout)
        headers = {"Host": _NCSI_HOST} if use_host_header else {}
        conn.request("GET", "/connecttest.txt", headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        conn.close()
        return resp.status == 200 and _NCSI_EXPECT in body
    except (OSError, ValueError, http.client.HTTPException):
        return False


def trigger_windows_ncsi_refresh(timeout: float = 5.0,
                                 adapter: NetworkAdapter | None = None) -> None:
    """认证成功后主动触发 Windows NCSI 检测，帮助刷新网络状态指示器。

    校园网 captive portal 会劫持微软的连通性检测请求，导致 Windows 任务栏
    仍显示「需要操作/无 Internet」。接口认证成功后网络实际已通，这里：
    1) 刷新 DNS 缓存；
    2) 访问微软 NCSI 检测点（域名失败时回退 IP 直连，绕开坏 DNS），
       并校验返回确实是 "Microsoft Connect Test"（避免被认证页劫持误判）。
    失败静默（不影响认证主流程）。
    """
    import subprocess
    # 1) 刷新 DNS 缓存
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=5,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
    except Exception:
        pass

    # 2) 域名探测（DNS 正常时首选）
    # 3) DNS 故障时回退 IP 直连（带 Host 头）
    # 整体再包一层异常保护：本函数承诺「失败静默，不影响认证主流程」，
    # 即使探测环节抛出未预期异常也不能打断 watch 守护循环。
    try:
        if _ncsi_probe(_NCSI_HOST, timeout, adapter=adapter):
            return
        for ip in _NCSI_IPS:
            if _ncsi_probe(ip, timeout, use_host_header=True, adapter=adapter):
                return
    except Exception:
        pass


# 断网（未认证）时用于触发网关劫持的探测目标：
# 域名优先（DNS 正常时），DNS 故障时回退公网 IP 直连（网关同样会劫持 HTTP 流量）。
_CAPTIVE_PROBE_IPS = ("223.5.5.5", "119.29.29.29", "180.76.76.76", "114.114.114.114")

# 劫持页里门户地址的常见写法（按可靠性排序；最后一条无捕获组，直接取整个 URL）
_PORTAL_REDIRECT_PATTERNS = (
    re.compile(r'location\.href\s*=\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'window\.location\s*=\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'location\.replace\(\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\'][^"\']*?url=([^"\']+)["\']', re.I),
    re.compile(r'<form[^>]+action=["\'](https?://[^"\']+)["\']', re.I),
    re.compile(r'https?://[^\s"\'<>]+/(?:eportal|portal)/[^\s"\'<>]*', re.I),
)


def _extract_portal_url(location: str, body: str) -> str:
    """从重定向响应里提取门户地址；找不到返回空串。

    兼容：302/301 Location 头、JS location.href / window.location / location.replace、
    meta refresh、登录表单 action，以及正文中出现的第一个 eportal/portal URL。
    """
    candidates: list[str] = []
    if location:
        candidates.append(location)
    text = body or ""
    for pattern in _PORTAL_REDIRECT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidates.append(match.group(1) if pattern.groups else match.group(0))
    for url in candidates:
        try:
            parts = urllib.parse.urlsplit(url.strip())
        except ValueError:
            continue
        host = parts.hostname
        if not host:
            continue
        port = parts.port
        if port and port not in (80, 443):
            return f"{host}:{port}"
        return host
    return ""


def detect_portal_host(probe_url: str = "http://www.baidu.com/",
                       adapter: NetworkAdapter | None = None,
                       timeout: float = 5.0) -> tuple[str | None, list[str]]:
    """断网（未认证）时访问外网，从网关劫持中自动提取门户地址。

    返回 (host, evidence)：
    - host：门户主机（非标准端口时形如 "10.0.0.1:8080"）；未取到为 None；
    - evidence：逐个探测目标的尝试记录，供界面提示与排障。

    DNS 故障时自动回退公网 IP 直连（网关照样劫持 HTTP 流量），
    支持多种劫持写法（Location / JS / meta refresh / 表单 action / eportal URL）。
    """
    parts = urllib.parse.urlsplit(probe_url)
    probe_host = parts.hostname or "www.baidu.com"
    probe_path = parts.path or "/"
    probe_scheme = parts.scheme or "http"

    # (label, host, port, path, use_https)
    targets: list[tuple[str, str, int, str, bool]] = [
        (probe_host, probe_host, parts.port or (443 if probe_scheme == "https" else 80),
         probe_path, probe_scheme == "https"),
    ]
    targets += [(ip, ip, 80, "/", False) for ip in _CAPTIVE_PROBE_IPS]

    evidence: list[str] = []
    headers = {"User-Agent": UA, "Connection": "close"}
    for label, host, port, path, use_https in targets:
        try:
            if use_https:
                conn = http.client.HTTPSConnection(
                    host, port, timeout=timeout, context=ssl.create_default_context())
            else:
                conn = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            status = response.status
            location = response.getheader("Location", "") or ""
            body = response.read(65536).decode("utf-8", errors="replace")
            conn.close()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            evidence.append(f"访问 {label} 失败：{type(exc).__name__}: {exc}")
            write_scrubbed_log(f"portal探测 {label} 连接失败: {exc}")
            continue

        portal = _extract_portal_url(location, body)
        if portal:
            evidence.append(f"访问 {label} → HTTP {status}，提取到门户地址 {portal}")
            write_scrubbed_log(f"portal探测 {label} -> HTTP {status}，门户地址 {portal}")
            return portal, evidence
        evidence.append(f"访问 {label} → HTTP {status}，未发现认证页跳转")
        write_scrubbed_log(f"portal探测 {label} -> HTTP {status}，无门户特征")
    return None, evidence
