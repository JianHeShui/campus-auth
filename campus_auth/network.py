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
from dataclasses import dataclass
from typing import Iterator, Sequence

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

    buffer_size = ctypes.c_uint32(15000)
    storage = ctypes.create_string_buffer(buffer_size.value)
    head = ctypes.cast(storage, ctypes.POINTER(_AdapterAddresses))
    # AF_INET，附带网关/多播跳过标志
    flags = 0x2 | 0x4
    if get_addresses(socket.AF_INET, flags, None, head, ctypes.byref(buffer_size)) != 0:
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
            return response.status == 200
    except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def trigger_windows_ncsi_refresh(timeout: float = 5.0) -> None:
    """认证成功后主动访问 Windows NCSI 检测点，帮助刷新网络状态指示器。

    校园网 captive portal 会劫持微软的连通性检测请求，导致 Windows 任务栏
    仍显示「需要操作/无 Internet」。接口认证成功后网络实际已通，这里主动访问
    一次微软检测点（www.msftconnecttest.com），促使 Windows 尽快判定「已连接」。
    失败静默（不影响认证主流程）。
    """
    try:
        conn = http.client.HTTPConnection("www.msftconnecttest.com", 80, timeout=timeout)
        conn.request("GET", "/connecttest.txt")
        resp = conn.getresponse()
        resp.read()
        conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        pass


def detect_portal_host(probe_url: str = "http://www.baidu.com/",
                       adapter: NetworkAdapter | None = None,
                       timeout: float = 5.0) -> str | None:
    """断网时访问外网，从网关劫持中自动提取门户主机地址。

    校园网 captive portal 两种劫持方式都支持：
    - 302 重定向：从 Location 头提取主机名；
    - 200 + JS 跳转：从响应体 location.href="http://门户/..." 提取主机名。
    若已联网（正常 200、无劫持），返回 None。
    """
    parts = urllib.parse.urlsplit(probe_url)
    host = parts.hostname or ""
    path = parts.path or "/"
    if not host:
        return None
    try:
        conn = BoundHTTPConnection(host, 80, adapter=adapter, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "campus-auth/0.1", "Connection": "close"})
        response = conn.getresponse()
        location = response.getheader("Location", "")
        body = response.read().decode("utf-8", errors="replace")
        conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return None

    # 1) 302 重定向的 Location 头
    if location:
        loc = urllib.parse.urlsplit(location)
        if loc.hostname:
            return loc.hostname

    # 2) 200 + JS location.href 跳转（H3C/深澜等网关）
    m = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', body)
    if m:
        loc = urllib.parse.urlsplit(m.group(1))
        if loc.hostname:
            return loc.hostname

    return None
