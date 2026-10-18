"""华三 CAS SSO 认证：访问认证页 → 提取密钥/execution → AES 加密 → POST 登录。

认证页前端（main.js）的登录逻辑：
    password = AES-ECB-PKCS7(croypto, 明文密码)   # 密钥 croypto 来自 login-croypto 元素
    POST /cas-sso/login
    参数: username, type=UsernamePassword, _eventId=submit, execution,
          croypto, password(密文), captcha_payload, geolocation
    成功: 302 → auth-success.html?ticket=...
"""
from __future__ import annotations

import http.client
import re
import time
import urllib.parse

from . import __version__
from .crypto import aes_ecb_pkcs7_encrypt_b64, has_crypto
from .logutil import mask, scrub, write_log
from .network import BoundHTTPConnection, NetworkAdapter

# 认证页 HTML 里承载动态参数的隐藏元素 id
ID_CROYPTO = "login-croypto"        # AES 密钥（base64）
ID_EXECUTION = "login-page-flowkey"  # CAS flow execution key

UA = f"campus-auth/{__version__}"


def _cas_log(msg: str) -> None:
    """写 CAS 调试日志（logutil 负责字段脱敏与轮转，失败静默）。"""
    write_log(scrub(msg))


def _extract_element(html: str, element_id: str) -> str | None:
    """从 HTML 提取指定 id 元素的内容（innerText 或 value 属性）。"""
    for pat in (
        rf'<[^>]+id=["\']{element_id}["\'][^>]*>(.*?)</[^>]+>',
        rf'<[^>]+id=["\']{element_id}["\'][^>]*value=["\'](.*?)["\']',
    ):
        m = re.search(pat, html, re.S)
        if m:
            return m.group(1).strip()
    return None


def _parse_set_cookie(headers) -> dict[str, str]:
    """解析一次响应里的全部 Set-Cookie，返回 name=value（丢弃 Path/HttpOnly 等属性）。

    门户可能同时下发多个 cookie（JSESSIONID、SESSION 等），全部保留；
    只取第一个会丢失会话，导致后续 CAS 登录被拒。
    """
    jar: dict[str, str] = {}
    for name, value in headers:
        if name.lower() != "set-cookie":
            continue
        pair = value.split(";", 1)[0].strip()
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        key, val = key.strip(), val.strip()
        if key:
            jar[key] = val
    return jar


class _CookieJar:
    """跨请求累积的 cookie 罐：CAS 流程每一步下发的 cookie 都带到后续请求。"""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def update(self, response) -> None:
        """从响应中吸收 Set-Cookie（读取失败静默）。"""
        try:
            headers = response.getheaders()
        except Exception:
            return
        self._items.update(_parse_set_cookie(headers))

    def header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._items.items())

    def names(self) -> list[str]:
        return list(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)


def _headers(jar: _CookieJar | None = None, referer: str | None = None) -> dict[str, str]:
    """构造请求头：自动带上 cookie 罐里的全部 cookie。"""
    headers = {"User-Agent": UA, "Connection": "close"}
    if jar:
        headers["Cookie"] = jar.header()
    if referer:
        headers["Referer"] = referer
    return headers


def _parse_json_body(text: str) -> dict:
    """把响应体解析成 JSON 对象；非 JSON/非对象返回空 dict。"""
    import json as _json
    try:
        value = _json.loads(text)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _summarize(value, limit: int = 160) -> str:
    """把工作流响应数据压成一行日志（敏感字段由 _cas_log 统一脱敏）。"""
    import json as _json
    try:
        text = _json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return text[:limit]


def _build_login_url(scheme: str, host: str, port: int, flow_session_id: str,
                     custom_page_id: str, nas_ip: str, user_ip: str) -> str:
    qs = urllib.parse.urlencode({
        "flowSessionId": flow_session_id,
        "customPageId": custom_page_id,
        "preview": "false",
        "appType": "normal",
        "language": "zh-CN",
        "timer": str(int(time.time() * 1000)),
        "nasIp": nas_ip,
        "userIp": user_ip,
        "accept-language": "zh-CN",
    })
    return f"{scheme}://{host}:{port}/cas-sso/login?{qs}"


def _workflow_step_ok(status: int, body: dict) -> tuple[bool, str]:
    """判断一个工作流步骤是否成功：HTTP 200 且业务 code 为 200（或缺失）。"""
    if status != 200:
        return False, f"HTTP {status}"
    code = body.get("code")
    if code not in (200, "200", None):
        message = body.get("message") or f"code={code}"
        return False, str(message)
    return True, ""


def _run_workflow(scheme: str, host: str, port: int, sid: str, credentials, adapter: NetworkAdapter | None,
                  jar: _CookieJar, timeout: float) -> dict:
    """CAS 登录后走锐捷工作流完成准入，返回 {ok, message, detail}。

    步骤：getCurrentNode → serviceSelection → serviceLogin → getCurrentNode → userOnline。
    每一步都校验 HTTP 状态与业务 code；userOnline 若返回 data.online 字段则必须为 True，
    避免以前"请求发出就算成功"的假成功判定。
    """
    import json as _json

    def post_json(path: str, body: dict):
        conn = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
        payload = _json.dumps(body).encode("utf-8")
        headers = _headers(jar, referer=f"{scheme}://{host}:{port}/portal/portal-main")
        headers["Content-Type"] = "application/json"
        conn.request("POST", path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", errors="replace")
        jar.update(resp)
        status = resp.status
        conn.close()
        return status, data

    # 运营商 → 服务名映射（服务名是英文，如 unicom/cmcc/ctcc）
    service = (getattr(credentials, "service", "") or "unicom").strip()
    svc_map = {
        "中国联通": "unicom", "联通": "unicom", "unicom": "unicom",
        "中国移动": "cmcc", "移动": "cmcc", "cmcc": "cmcc",
        "中国电信": "ctcc", "电信": "ctcc", "ctcc": "ctcc",
        "校园网": "unicom", "教育网": "unicom",
    }
    service = svc_map.get(service, service or "unicom")

    steps = [
        ("getCurrentNode", "/eportal/workFlow/getCurrentNode",
         {"sessionId": sid, "flowKey": "portal_auth"}),
        ("serviceSelection", "/eportal/network/serviceSelection", {"sessionId": sid}),
        ("serviceLogin", "/eportal/network/serviceLogin", {"sessionId": sid, "service": service}),
        ("getCurrentNode2", "/eportal/workFlow/getCurrentNode",
         {"sessionId": sid, "flowKey": "portal_auth"}),
        ("userOnline", "/eportal/network/userOnline", {"sessionId": sid}),
    ]

    detail: dict[str, dict] = {}
    for label, path, body in steps:
        try:
            status, text = post_json(path, body)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            _cas_log(f"工作流 {label} 请求失败: {exc}")
            return {"ok": False, "message": f"工作流 {label} 请求失败: {exc}", "detail": detail}
        parsed = _parse_json_body(text)
        detail[label] = {"status": status, "code": parsed.get("code"), "data": parsed.get("data")}
        _cas_log(f"工作流 {label} -> HTTP {status} code={parsed.get('code')!r} "
                 f"data={_summarize(parsed.get('data'))}")
        ok, message = _workflow_step_ok(status, parsed)
        if not ok:
            return {"ok": False, "message": f"工作流 {label} 失败：{message}", "detail": detail}
        if label == "userOnline":
            data_part = parsed.get("data")
            if isinstance(data_part, dict) and "online" in data_part and data_part.get("online") is not True:
                return {
                    "ok": False,
                    "message": f"工作流 userOnline 未上线（online={data_part.get('online')!r}）",
                    "detail": detail,
                }
    return {"ok": True, "message": "已上线", "detail": detail}


def authenticate_cas(profile, credentials, adapter: NetworkAdapter | None,
                     timeout: float = 10) -> dict:
    """执行华三 CAS SSO 认证，返回 {ok, message, detail}。"""
    if not has_crypto():
        return {"ok": False, "message": "缺少 AES 加密库（pycryptodome），无法完成 CAS 认证", "detail": {}}

    host = profile.host
    port = profile.port
    scheme = getattr(profile, "scheme", "http") or "http"  # 支持 HTTPS CAS 门户
    jar = _CookieJar()
    probe_headers = _headers()

    # 1) captive 探测：访问外网，网关劫持返回跳转到 /eportal/index.jsp?wlanuserip=...&wlanacname=...
    probe_url = getattr(profile, "redirect_probe_url", None) or "http://www.baidu.com/"
    probe_parts = urllib.parse.urlsplit(probe_url)
    probe_host = probe_parts.hostname or "www.baidu.com"
    probe_path = probe_parts.path or "/"

    # 探测目标：优先域名，DNS 故障时回退到公网 IP 直连（网关照样劫持 IP 的 HTTP 流量）
    probe_targets = [(probe_host, probe_path)]
    probe_targets += [(ip, "/") for ip in ("223.5.5.5", "119.29.29.29", "180.76.76.76", "114.114.114.114")]

    probe_body = ""
    last_exc: Exception | None = None
    for target_host, target_path in probe_targets:
        try:
            conn = BoundHTTPConnection(target_host, 80, adapter=adapter, timeout=timeout)
            conn.request("GET", target_path, headers=probe_headers)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            conn.close()
            probe_body = body
            # 找到含网关劫持跳转（location.href）的响应即可停
            if "location.href" in body or "location=\"" in body or "eportal/index.jsp" in body:
                _cas_log(f"CAS captive探测(目标={target_host}) 命中网关劫持")
                break
        except (OSError, http.client.HTTPException) as exc:
            last_exc = exc
            _cas_log(f"CAS captive探测 {target_host} 失败: {exc}")
            continue

    if not probe_body:
        _cas_log(f"CAS captive探测全部失败: {last_exc}")
        return {"ok": False, "message": f"captive探测失败: {last_exc}", "detail": {}}

    m = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', probe_body)
    redirect_url = m.group(1) if m else ""
    _cas_log(f"CAS 网关跳转地址: {redirect_url!r}")
    wlanuserip = _param(redirect_url, "wlanuserip")
    wlanacname = _param(redirect_url, "wlanacname")
    _cas_log(f"CAS wlanuserip={wlanuserip!r} wlanacname={wlanacname!r}")
    if not wlanuserip:
        _cas_log(f"CAS 劫持HTML前500: {probe_body[:500]!r}")
        return {"ok": False, "message": "未能从网关劫持页提取 wlanuserip", "detail": {}}

    # 2) 访问 /eportal/index.jsp，跟踪跳转到 CAS 登录页
    flow_session_id = custom_page_id = nas_ip = user_ip = ""
    login_html = ""
    index_path = f"/eportal/index.jsp?wlanuserip={wlanuserip}&wlanacname={urllib.parse.quote(wlanacname)}"
    try:
        conn2 = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
        conn2.request("GET", index_path, headers=_headers(jar))
        resp2 = conn2.getresponse()
        status2 = resp2.status
        loc2 = resp2.getheader("Location", "")
        body2 = resp2.read().decode("utf-8", errors="replace")
        jar.update(resp2)
        conn2.close()
        _cas_log(f"CAS /eportal/index.jsp -> HTTP {status2} Location={loc2!r}")
        _cas_log(f"  index正文前500: {body2[:500]!r}")

        flow_session_id = _param(loc2, "flowSessionId") or _param(body2, "flowSessionId")
        custom_page_id = _param(loc2, "customPageId") or _param(body2, "customPageId")
        nas_ip = _param(loc2, "nasIp") or _param(body2, "nasIp")
        user_ip = _param(loc2, "userIp") or _param(body2, "userIp") or wlanuserip
        session_id = _param(loc2, "sessionId") or _param(body2, "sessionId")

        # /eportal/index.jsp 可能用 302 或 JS location.href 跳转
        current_url = loc2 or ""
        if not current_url:
            m2 = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', body2)
            current_url = m2.group(1) if m2 else ""

        # 跟踪多级跳转（/eportal/index.jsp → /portal/portal-main → CAS 登录页 → ...），最多 5 级
        login_html = body2
        for hop in range(5):
            if not current_url:
                break
            clean_url = current_url.replace(" ", "%20")  # accessTime 参数含空格
            _cas_log(f"CAS 跳转[{hop}] {clean_url[:200]!r}")
            try:
                conn3 = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
                conn3.request("GET", clean_url, headers=_headers(jar))
                resp3 = conn3.getresponse()
                s3 = resp3.status
                loc3 = resp3.getheader("Location", "")
                b3 = resp3.read().decode("utf-8", errors="replace")
                jar.update(resp3)
                conn3.close()
            except (OSError, http.client.HTTPException) as exc:
                _cas_log(f"CAS 跳转[{hop}] 请求失败: {exc}")
                break
            _cas_log(f"  -> HTTP {s3} Location={loc3[:200]!r}")
            flow_session_id = flow_session_id or _param(loc3, "flowSessionId") or _param(b3, "flowSessionId")
            custom_page_id = custom_page_id or _param(loc3, "customPageId") or _param(b3, "customPageId")
            nas_ip = nas_ip or _param(loc3, "nasIp") or _param(b3, "nasIp")
            user_ip = user_ip or _param(loc3, "userIp") or _param(b3, "userIp")
            session_id = session_id or _param(loc3, "sessionId") or _param(b3, "sessionId")
            if s3 in (301, 302, 303, 307, 308) and loc3:
                current_url = loc3
                continue
            login_html = b3
            break
    except (OSError, http.client.HTTPException) as exc:
        _cas_log(f"CAS 访问 eportal/index.jsp 失败: {exc}")
        return {"ok": False, "message": f"访问 eportal/index.jsp 失败: {exc}", "detail": {}}

    # 2) 从登录页 HTML 提取 croypto 密钥与 execution
    # 若 login_html 是 SPA 壳（无 croypto），直接访问 /pc/center 登录页
    if not _extract_element(login_html, ID_CROYPTO):
        center_url = (f"/pc/center?flowSessionId={session_id or flow_session_id}"
                      f"&customPageId={custom_page_id}&preview=false&appType=normal"
                      f"&language=zh-CN&nasIp={nas_ip}&userIp={user_ip}")
        _cas_log(f"CAS 尝试 /pc/center: {center_url[:180]!r}")
        try:
            conn4 = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
            conn4.request("GET", center_url, headers=_headers(jar))
            resp4 = conn4.getresponse()
            jar.update(resp4)
            login_html = resp4.read().decode("utf-8", errors="replace")
            conn4.close()
            _cas_log(f"  /pc/center 收到 cookie: {jar.names()}")
        except (OSError, http.client.HTTPException) as exc:
            _cas_log(f"  /pc/center 访问失败: {exc}")

    croypto = _extract_element(login_html, ID_CROYPTO) or ""
    execution = _extract_element(login_html, ID_EXECUTION) or ""
    _cas_log(f"CAS 参数: flowSessionId={flow_session_id!r} sessionId={session_id!r} customPageId={custom_page_id!r} nasIp={nas_ip!r} userIp={user_ip!r}")
    _cas_log(f"CAS 提取: croypto={mask(croypto)} execution长度={len(execution)}")
    if not croypto:
        _cas_log(f"CAS 登录页HTML前500字节: {login_html[:500]!r}")
        return {"ok": False, "message": "未能从认证页提取 croypto 密钥", "detail": {"flowSessionId": flow_session_id}}
    if not execution:
        _cas_log(f"CAS 登录页HTML前500字节: {login_html[:500]!r}")
        return {"ok": False, "message": "未能从认证页提取 execution", "detail": {"flowSessionId": flow_session_id}}

    # 3) AES 加密密码（captcha_payload 默认空对象）
    try:
        enc_password = aes_ecb_pkcs7_encrypt_b64(croypto, credentials.password)
        enc_captcha = aes_ecb_pkcs7_encrypt_b64(croypto, "{}")
    except Exception as exc:
        return {"ok": False, "message": f"密码加密失败: {exc}", "detail": {}}

    # 4) POST /cas-sso/login 提交
    body_fields = {
        "username": credentials.username,
        "type": "UsernamePassword",
        "_eventId": "submit",
        "geolocation": "",
        "execution": execution,
        "captcha_code": "",
        "croypto": croypto,
        "password": enc_password,
        "captcha_payload": enc_captcha,
    }
    payload = urllib.parse.urlencode(body_fields).encode("utf-8")
    login_url = _build_login_url(scheme, host, port, session_id or flow_session_id,
                                 custom_page_id, nas_ip, user_ip)
    _cas_log(f"CAS 登录URL: {login_url[:200]!r}")
    _cas_log(f"CAS 提交字段: username={mask(credentials.username)} croypto={mask(croypto)} "
             f"password=密文({len(enc_password)}字符) execution长度={len(execution)}")
    referer = (f"{scheme}://{host}:{port}/pc/center?flowSessionId={session_id or flow_session_id}"
               f"&customPageId={custom_page_id}")
    post_headers = _headers(jar, referer=referer)
    post_headers["Content-Type"] = "application/x-www-form-urlencoded"
    post_headers["Origin"] = f"{scheme}://{host}:{port}"
    try:
        conn3 = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
        conn3.request("POST", urllib.parse.urlsplit(login_url).path + "?" + urllib.parse.urlsplit(login_url).query,
                      body=payload, headers=post_headers)
        resp3 = conn3.getresponse()
        status = resp3.status
        loc = resp3.getheader("Location", "")
        resp_body = resp3.read().decode("utf-8", errors="replace")
        jar.update(resp3)
        conn3.close()
    except (OSError, http.client.HTTPException) as exc:
        _cas_log(f"CAS 登录请求失败: {exc}")
        return {"ok": False, "message": f"登录请求失败: {exc}", "detail": {}}

    _cas_log(f"CAS 登录 -> HTTP {status} Location={loc!r}")
    # 在响应体里找错误关键词，判断失败原因
    for kw in ("密码", "错误", "失败", "password", "error", "invalid", "认证"):
        if kw.lower() in resp_body.lower():
            idx = resp_body.lower().find(kw.lower())
            _cas_log(f"  响应体含关键词 {kw!r}: ...{resp_body[max(0,idx-40):idx+40]!r}...")
    _cas_log(f"  登录响应体前500字节: {resp_body[:500]!r}")
    if status in (301, 302, 303, 307, 308) and ("auth-success" in loc or "ticket=" in loc):
        ticket = _param(loc, "ticket")
        _cas_log(f"CAS 成功 ticket={mask(ticket)}")
        # 访问 auth-success.html（服务端在此验证 ticket 完成身份认证）
        try:
            clean_loc = loc.replace(" ", "%20")
            succ_headers = _headers(jar, referer=f"{scheme}://{host}:{port}/pc/center")
            succ_headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                          "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")
            conn5 = BoundHTTPConnection(host, port, adapter=adapter, timeout=timeout)
            conn5.request("GET", clean_loc, headers=succ_headers)
            resp5 = conn5.getresponse()
            resp5.read()
            jar.update(resp5)
            conn5.close()
            _cas_log(f"auth-success 响应 HTTP {resp5.status}")
        except (OSError, http.client.HTTPException) as exc:
            _cas_log(f"auth-success.html 访问失败: {exc}")

        # CAS 登录成功后，走锐捷工作流完成准入（userOnline 上线）
        sid = session_id or flow_session_id
        detail = {"location": loc, "ticket": mask(ticket)}
        if sid:
            flow = _run_workflow(scheme, host, port, sid, credentials, adapter, jar, timeout)
            if flow.get("ok"):
                return {"ok": True, "message": "认证成功（已上线）",
                        "detail": {**detail, "online_confirmed": True}}
            _cas_log(f"CAS 登录成功但工作流上线失败: {flow.get('message')}")
            return {"ok": True, "message": "CAS 认证成功（上线状态待确认）",
                    "detail": {**detail, "online_confirmed": False,
                               "workflow_error": flow.get("message", "")}}
        return {"ok": True, "message": "CAS 认证成功（上线状态待确认）",
                "detail": {**detail, "online_confirmed": False}}
    return {"ok": False, "message": f"CAS 登录失败 (HTTP {status})", "detail": {"location": loc, "body": resp_body[:500]}}


def _param(text: str, name: str) -> str:
    """从 URL 或 HTML 文本里提取指定查询参数。"""
    if not text:
        return ""
    # URL 查询串
    q = urllib.parse.urlsplit(text).query
    vals = urllib.parse.parse_qs(q).get(name)
    if vals:
        return vals[0]
    # 文本里的 name=value / "name":"value"
    m = re.search(rf'["\']?{name}["\']?\s*[:=]\s*["\']([^"\'&]+)["\']', text)
    return m.group(1) if m else ""
