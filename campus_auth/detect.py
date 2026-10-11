"""门户类型自动探测：访问门户地址，按可观测特征识别厂商/类型。

纯标准库，只做 GET 探测、不提交任何凭据。识别依据：
- 锐捷 SAM+：/portal/ SPA（base href、__PLATFORM_SSO__、cas-sso）+ config.js 里
  「锐捷/smpdomain/enableCompliance」+ /eportal/adaptor/* 返回「Required request parameter」；
- 深澜 Srun：认证 URL 带 wlanuserip / wlanacname，入口 /eportal/index.jsp；
- Dr.COM / 华为：品牌字样。
"""
from __future__ import annotations

import http.client
import ssl
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


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


def _get(host: str, port: int, scheme: str, path: str, timeout: float = 6) -> tuple[int | None, dict, str]:
    """GET 一个路径，返回 (status, headers, body)；失败返回 (None, {}, "")。"""
    try:
        if scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": UA, "Accept": "*/*"})
        resp = conn.getresponse()
        status = resp.status
        headers = dict(resp.getheaders())
        body = resp.read(65536).decode("utf-8", "replace")
        conn.close()
        return status, headers, body
    except Exception:
        return None, {}, ""


def probe_portal(address: str, timeout: float = 6) -> dict:
    """探测一个门户地址，返回识别结果。"""
    host, port, scheme = parse_address(address)
    if not host:
        return {"recognized": False, "type": None, "template": None, "mode": "simple",
                "evidence": ["地址无法解析"], "message": "地址无法解析"}

    evidence: list[str] = []

    # 1) 根路径
    status, headers, _ = _get(host, port, scheme, "/", timeout)
    evidence.append(f"GET / → {status if status else '不可达'}")
    location = headers.get("Location", "") if headers else ""

    # 2) 锐捷 portal SPA 入口
    _, _, portal = _get(host, port, scheme, "/portal/", timeout)
    if not portal:
        _, _, portal = _get(host, port, scheme,
                            "/portal/entry/pc/authenticate;flowParams=undefined;from=", timeout)

    # 3) 锐捷 config.js
    _, _, config = _get(host, port, scheme, "/portal/assets/config.js", timeout)

    # 4) 深澜入口
    _, _, srun = _get(host, port, scheme, "/eportal/index.jsp", timeout)

    # 5) eportal 在线接口（锐捷/深澜都有）
    eportal_status, _, eportal_api = _get(host, port, scheme, "/eportal/adaptor/getOnlineUserInfo", timeout)
    if eportal_status:
        evidence.append(f"GET /eportal/adaptor/getOnlineUserInfo → {eportal_status}")

    # 特征汇总
    all_text = " ".join([portal, config, srun, eportal_api]).lower()
    has_session_guard = "required request parameter" in eportal_api.lower() or \
                        "sessionid" in eportal_api.lower()

    # ---- 分类 ----
    # 锐捷 SAM+：config.js 品牌/聚合层 + SPA 的 SSO 平台标记 + 接口会话门禁
    if ("锐捷" in config or "smpdomain" in config or "enablecompliance" in config
            or "__platform_sso__" in portal.lower() or "cas-sso" in portal.lower()):
        return {
            "recognized": True, "type": "锐捷 SAM+", "template": "锐捷 SAM+（工作流）",
            "mode": "workflow",
            "evidence": evidence + ["config.js 含锐捷/聚合层标记", "SPA 含 CAS-SSO 平台标记"],
            "message": "检测到锐捷 SAM+ 门户，已按工作流模式填充。",
        }
    # 深澜 Srun：认证 URL 参数 + eportal/index.jsp 入口
    if ("wlanuserip" in all_text or "wlanacname" in all_text or "eportal/index.jsp" in all_text
            or "/eportal/index.jsp" in srun):
        return {
            "recognized": True, "type": "深澜 Srun", "template": "通用（简单登录）",
            "mode": "simple",
            "evidence": evidence + ["检测到 wlanuserip/wlanacname 或 eportal/index.jsp 入口"],
            "message": "检测到深澜 Srun 门户，已按通用登录模式填充（接口细节需按实际微调）。",
        }
    # Dr.COM
    if "dr.com" in all_text or "drcom" in all_text:
        return {
            "recognized": True, "type": "Dr.COM", "template": "通用（简单登录）",
            "mode": "simple",
            "evidence": evidence + ["页面含 Dr.COM 品牌字样"],
            "message": "检测到 Dr.COM 门户，暂未内置专用模板，已按通用登录模式填充。",
        }
    # 华为
    if "华为" in all_text or "huawei" in all_text or "agile controller" in all_text:
        return {
            "recognized": True, "type": "华为", "template": "通用（简单登录）",
            "mode": "simple",
            "evidence": evidence + ["页面含华为/Huawei 品牌字样"],
            "message": "检测到华为门户，暂未内置专用模板，已按通用登录模式填充。",
        }
    # eportal 系（有会话门禁但品牌未识别）
    if has_session_guard:
        return {
            "recognized": True, "type": "ePortal 系（锐捷/深澜）", "template": "锐捷 SAM+（工作流）",
            "mode": "workflow",
            "evidence": evidence + ["/eportal 接口存在会话门禁（sessionId 必填）"],
            "message": "检测到 ePortal 系门户（锐捷/深澜），已按工作流模式填充，建议核对接口路径。",
        }
    return {
        "recognized": False, "type": None, "template": "通用（简单登录）", "mode": "simple",
        "evidence": evidence,
        "message": "未能自动识别门户类型，已按「通用（简单登录）」填充；可展开高级设置手动调整。",
    }
