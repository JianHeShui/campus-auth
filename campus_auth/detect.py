"""门户类型自动探测：并发探测门户特征，识别厂商/类型。

纯标准库，只做 GET 探测、不提交任何凭据。识别依据：
- 华三 CAS SSO：/sso-public/cas-login-new/main.js 返回 200 且正文确实是 JavaScript。
  **必须校验内容**：不少 SPA 门户对任意路径都回 200 index.html，只看状态码会把
  普通锐捷门户误判成 CAS，从而生成错误的认证配置；
- 锐捷 SAM+：/portal/ SPA（base href、__PLATFORM_SSO__、cas-sso）+ config.js 里
  「锐捷/smpdomain/enableCompliance」+ /eportal/adaptor/* 返回「Required request parameter」；
- 深澜 Srun：认证 URL 带 wlanuserip / wlanacname，入口 /eportal/index.jsp；
- Dr.COM / 华为：品牌字样。

全部探测请求并发执行（最坏耗时从 N×timeout 降为约 1×timeout）；
HTTPS 证书校验失败时（校园网自签名门户常见）自动用宽松模式重试一次。
"""
from __future__ import annotations

import concurrent.futures
import http.client
import ssl
import time
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

# 一次并发探测的全部特征路径（key → path）
_PROBE_PATHS = {
    "root": "/",
    "portal": "/portal/",
    "portal_entry": "/portal/entry/pc/authenticate;flowParams=undefined;from=",
    "config": "/portal/assets/config.js",
    "srun": "/eportal/index.jsp",
    "eportal": "/eportal/adaptor/getOnlineUserInfo",
    "cas": "/sso-public/cas-login-new/main.js",
}

_JS_MARKERS = ("function", "var ", "const ", "let ", "=>", "window.", "webpack",
               "system.register", "use strict", "export ")
_HTML_MARKERS = ("<!doctype html", "<html", "<head", "<body")


def parse_address(text: str) -> tuple[str, int, str]:
    """把地址解析成 (host, port, scheme)。"""
    text = text.strip()
    if "://" not in text:
        text = "http://" + text
    parts = urllib.parse.urlsplit(text)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    scheme = parts.scheme or "http"
    return host, port, scheme


def _request(host: str, port: int, scheme: str, path: str, timeout: float,
             insecure: bool = False) -> tuple[int | None, dict, str]:
    """执行一次 GET；失败返回 (None, {}, "")。insecure=True 时不校验 HTTPS 证书。"""
    try:
        if scheme == "https":
            context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": UA, "Accept": "*/*"})
        resp = conn.getresponse()
        status = resp.status
        headers = {key.lower(): value for key, value in resp.getheaders()}
        body = resp.read(65536).decode("utf-8", "replace")
        conn.close()
        return status, headers, body
    except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
        return None, {}, ""


def _get(host: str, port: int, scheme: str, path: str,
         timeout: float = 6) -> tuple[int | None, dict, str]:
    """GET 一个路径；HTTPS 证书校验失败（自签名门户常见）时用宽松模式重试一次。"""
    status, headers, body = _request(host, port, scheme, path, timeout)
    if status is None and scheme == "https":
        return _request(host, port, scheme, path, timeout, insecure=True)
    return status, headers, body


def _probe_all(host: str, port: int, scheme: str, timeout: float) -> dict[str, tuple]:
    """并发探测全部特征路径，返回 {key: (status, headers, body)}。"""
    results: dict[str, tuple] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_PROBE_PATHS)) as pool:
        futures = {
            pool.submit(_get, host, port, scheme, path, timeout): key
            for key, path in _PROBE_PATHS.items()
        }
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = (None, {}, "")
    return results


def _looks_like_javascript(status: int | None, headers: dict, body: str) -> bool:
    """判断响应是否真的是 JS 资源（防止 SPA 对任意路径回 200 HTML 造成误判）。"""
    if status != 200 or not body:
        return False
    content_type = str(headers.get("content-type", "")).lower()
    if "javascript" in content_type or "ecmascript" in content_type:
        return True
    head = body[:800].lower()
    if any(marker in head for marker in _HTML_MARKERS):
        return False
    return any(marker in head for marker in _JS_MARKERS)


def probe_portal(address: str, timeout: float = 6) -> dict:
    """探测一个门户地址，返回识别结果（附耗时 elapsed 秒）。"""
    host, port, scheme = parse_address(address)
    if not host:
        return {"recognized": False, "type": None, "template": None, "mode": "simple",
                "evidence": ["地址无法解析"], "message": "地址无法解析", "elapsed": 0.0}

    started = time.monotonic()
    results = _probe_all(host, port, scheme, timeout)

    root_status, root_headers, root_body = results["root"]
    _, _, portal = results["portal"]
    if not portal:
        _, _, portal = results["portal_entry"]
    _, _, config = results["config"]
    _, _, srun = results["srun"]
    eportal_status, _, eportal_api = results["eportal"]
    cas_status, cas_headers, cas_body = results["cas"]

    evidence: list[str] = [f"GET / → {root_status if root_status else '不可达'}"]
    if eportal_status:
        evidence.append(f"GET /eportal/adaptor/getOnlineUserInfo → {eportal_status}")
    if cas_status:
        evidence.append(f"GET /sso-public/cas-login-new/main.js → {cas_status}")

    all_text = " ".join([root_body, portal, config, srun, eportal_api]).lower()
    has_session_guard = "required request parameter" in eportal_api.lower() or \
                        "sessionid" in eportal_api.lower()
    cas_confirmed = _looks_like_javascript(cas_status, cas_headers, cas_body)
    elapsed = round(time.monotonic() - started, 2)

    # ---- 分类 ----
    # 华三 CAS SSO：必须是「200 + 真 JS 正文」，避免 SPA 万能 200 误判
    if cas_confirmed:
        return {
            "recognized": True, "type": "华三 CAS SSO", "template": "华三 CAS SSO（加密）",
            "mode": "cas",
            "evidence": evidence + ["CAS 登录组件返回 JavaScript（内容校验通过）"],
            "message": "检测到华三 CAS SSO 门户，已按 CAS 加密模式填充。",
            "elapsed": elapsed,
        }
    # 锐捷 SAM+：config.js 品牌/聚合层 + SPA 的 SSO 平台标记 + 接口会话门禁
    if ("锐捷" in config or "smpdomain" in config or "enablecompliance" in config
            or "__platform_sso__" in portal.lower()):
        return {
            "recognized": True, "type": "锐捷 SAM+", "template": "锐捷 SAM+（工作流）",
            "mode": "workflow",
            "evidence": evidence + ["config.js 含锐捷/聚合层标记", "SPA 含 SSO 平台标记"],
            "message": "检测到锐捷 SAM+ 门户，已按工作流模式填充。",
            "elapsed": elapsed,
        }
    # 深澜 Srun：认证 URL 参数 + eportal/index.jsp 入口
    if ("wlanuserip" in all_text or "wlanacname" in all_text or "eportal/index.jsp" in all_text
            or "/eportal/index.jsp" in srun):
        return {
            "recognized": True, "type": "深澜 Srun", "template": "通用（简单登录）",
            "mode": "simple",
            "evidence": evidence + ["检测到 wlanuserip/wlanacname 或 eportal/index.jsp 入口"],
            "message": "检测到深澜 Srun 门户，已按通用登录模式填充（接口细节需按实际微调）。",
            "elapsed": elapsed,
        }
    # Dr.COM
    if "dr.com" in all_text or "drcom" in all_text:
        return {
            "recognized": True, "type": "Dr.COM", "template": "通用（简单登录）",
            "mode": "simple",
            "evidence": evidence + ["页面含 Dr.COM 品牌字样"],
            "message": "检测到 Dr.COM 门户，暂未内置专用模板，已按通用登录模式填充。",
            "elapsed": elapsed,
        }
    # 华为
    if "华为" in all_text or "huawei" in all_text or "agile controller" in all_text:
        return {
            "recognized": True, "type": "华为", "template": "通用（简单登录）",
            "mode": "simple",
            "evidence": evidence + ["页面含华为/Huawei 品牌字样"],
            "message": "检测到华为门户，暂未内置专用模板，已按通用登录模式填充。",
            "elapsed": elapsed,
        }
    # eportal 系（有会话门禁但品牌未识别）
    if has_session_guard:
        return {
            "recognized": True, "type": "ePortal 系（锐捷/深澜）", "template": "锐捷 SAM+（工作流）",
            "mode": "workflow",
            "evidence": evidence + ["/eportal 接口存在会话门禁（sessionId 必填）"],
            "message": "检测到 ePortal 系门户（锐捷/深澜），已按工作流模式填充，建议核对接口路径。",
            "elapsed": elapsed,
        }
    return {
        "recognized": False, "type": None, "template": "通用（简单登录）", "mode": "simple",
        "evidence": evidence,
        "message": "未能自动识别门户类型，已按「通用（简单登录）」填充；可展开高级设置手动调整。",
        "elapsed": elapsed,
    }
