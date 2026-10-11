"""认证客户端：接口直连完成校园网认证（工作流模型，不驱动浏览器）。

认证是"工作流状态机"：账号密码经 updateUserSession 的 updateSessionData 提交，
服务确认走 setService，在线判定走 getOnlineUserInfo。
"""
from __future__ import annotations

import http.client
import json
import urllib.parse
from dataclasses import dataclass, field

from .network import BoundHTTPConnection, NetworkAdapter, https_reachable
from .portal import PortalProfile
from .state import AuthState


class AuthError(RuntimeError):
    """可向用户展示的认证错误。"""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    service: str = ""

    def redact(self, text: str) -> str:
        for value in (self.password, self.username):
            if value:
                text = text.replace(value, "[已隐藏]")
        return text


@dataclass
class AuthResult:
    state: AuthState
    message: str = ""
    detail: dict = field(default_factory=dict)


def _parse_json(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _deep_get(mapping: dict, dotted_path: str):
    current: object = mapping
    for key in dotted_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _extract_session_id(url: str, field_name: str) -> str | None:
    query = urllib.parse.urlsplit(url).query
    params = urllib.parse.parse_qs(query)
    values = params.get(field_name)
    return values[0] if values else None


class Client:
    """绑定到指定网卡的认证客户端。"""

    def __init__(self, profile: PortalProfile, *, adapter: NetworkAdapter | None = None,
                 timeout: float = 10):
        self.profile = profile
        self.adapter = adapter
        self.timeout = timeout

    # ---- 底层请求 ----

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 query: dict | None = None, timeout: float | None = None) -> tuple[int, dict]:
        host = self.profile.host
        port = self.profile.port
        timeout = timeout or self.timeout

        full_path = path
        if query:
            full_path = f"{path}?{urllib.parse.urlencode(query)}"

        payload = json.dumps(body).encode("utf-8") if body is not None else None
        conn = BoundHTTPConnection(host, port, adapter=self.adapter, timeout=timeout)
        headers = {
            "User-Agent": "campus-auth/0.1",
            "Accept": "application/json, text/plain, */*",
            "Origin": f"{self.profile.scheme}://{host}:{port}",
            "Referer": f"{self.profile.scheme}://{host}:{port}/portal/",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, full_path, body=payload, headers=headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, _parse_json(data)
        except (OSError, http.client.HTTPException) as exc:
            raise AuthError(f"门户请求失败: {exc}") from exc
        finally:
            conn.close()

    def _get(self, path: str, query: dict | None = None) -> tuple[int, dict]:
        return self._request("GET", path, query=query)

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        return self._request("POST", path, body=body)

    def _ok(self, body: dict) -> bool:
        return body.get("code") in (200, None)

    # ---- 会话获取 ----

    def acquire_session(self) -> str | None:
        """通过 captive 重定向拿到 sessionId；已联网时返回 None（表示无需认证）。"""
        if self.profile.session_mode == "manual":
            return None
        return self._captive_session()

    def _captive_session(self) -> str | None:
        """访问外部 http 地址，看网关是否把浏览器劫持回门户。

        - 被劫持到门户 URL：从 Location 查询串解析 sessionId。
        - 正常放行（已联网）：返回 None。
        """
        probe_url = self.profile.redirect_probe_url
        parts = urllib.parse.urlsplit(probe_url)
        host = parts.hostname or ""
        path = parts.path or "/"
        if not host:
            return None
        try:
            conn = BoundHTTPConnection(host, 80, adapter=self.adapter, timeout=self.timeout)
            conn.request("GET", path, headers={"User-Agent": "campus-auth/0.1", "Connection": "close"})
            response = conn.getresponse()
            status = response.status
            location = response.getheader("Location", "")
            response.read()
            conn.close()
        except (OSError, http.client.HTTPException):
            return None
        if status in (301, 302, 303, 307, 308) and location and self.profile.host in location:
            return _extract_session_id(location, self.profile.session_field)
        return None

    # ---- 工作流认证 ----

    def check_online(self, session_id: str) -> bool:
        """门户在线接口是否报告已登录。"""
        field = self.profile.session_field
        status, body = self._get(self.profile.endpoint("online_info"), query={field: session_id})
        if status != 200:
            return False
        return _deep_get(body, self.profile.online_path_field) == self.profile.online_success_value

    def get_current_node(self, session_id: str, flow_key: str | None = None) -> dict:
        """取当前工作流节点（返回 data 部分）。"""
        field = self.profile.session_field
        body = {field: session_id, "flowKey": flow_key or self.profile.flow_key}
        status, resp = self._post(self.profile.endpoint("get_current_node"), body)
        if status != 200:
            raise AuthError(f"获取当前节点失败 (HTTP {status})")
        if not self._ok(resp):
            raise AuthError(f"获取当前节点失败: {resp.get('message', '')}")
        return resp.get("data") or {}

    def submit_credentials(self, session_id: str, credentials: Credentials) -> dict:
        """提交账号密码到工作流（updateUserSession）。"""
        fields = self.profile.credential_fields
        field = self.profile.session_field
        payload = {
            "result": self.profile.result_value,
            field: session_id,
            "updateSessionData": {
                fields["username"]: credentials.username,
                fields["password"]: credentials.password,
                fields["auth_type"]: self.profile.auth_type,
            },
        }
        status, resp = self._post(self.profile.endpoint("update_session"), payload)
        if status != 200 or not self._ok(resp):
            message = str(resp.get("message") or f"HTTP {status}")
            return {"ok": False, "message": message, "body": resp}
        return {"ok": True, "message": resp.get("message", ""), "body": resp}

    def list_services(self, session_id: str) -> list[str]:
        """获取可用服务列表。"""
        field = self.profile.session_field
        status, resp = self._post(self.profile.endpoint("service_selection"), {field: session_id})
        if status != 200:
            raise AuthError(f"服务列表请求失败 (HTTP {status})")
        if not self._ok(resp):
            raise AuthError(f"获取服务失败: {resp.get('message', '')}")
        data = resp.get("data") or {}
        services: list[str] = []
        raw = data if isinstance(data, list) else data.get("services", data.get("list", []))
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    services.append(item)
                elif isinstance(item, dict):
                    for key in ("serviceName", "service", "name"):
                        if item.get(key):
                            services.append(str(item[key]))
                            break
        return services

    def set_service(self, session_id: str, service_name: str) -> dict:
        """确认服务/运营商。"""
        fields = self.profile.service_fields
        field = self.profile.session_field
        payload = {field: session_id, fields["service"]: service_name}
        status, resp = self._post(self.profile.endpoint("set_service"), payload)
        if status != 200:
            return {"ok": False, "message": f"HTTP {status}", "body": resp}
        if not self._ok(resp):
            return {"ok": False, "message": str(resp.get("message", "")), "body": resp}
        data = resp.get("data") or {}
        switch = data.get("switchResult", "")
        if switch == "success":
            return {"ok": True, "message": "服务确认成功", "body": resp}
        return {"ok": False, "message": f"服务确认失败: {data.get('message', switch)}", "body": resp}

    def authenticate(self, credentials: Credentials, session_id: str | None = None) -> AuthResult:
        """完整认证入口，按画像的 auth_mode 分派到工作流或通用登录。"""
        session_id = session_id or self.acquire_session()

        if session_id and self.check_online(session_id):
            return AuthResult(AuthState.ONLINE, "当前已在线，无需重复登录")

        if self.profile.auth_mode == "simple":
            return self._authenticate_simple(credentials, session_id)

        if not session_id:
            if self._internet_ok():
                return AuthResult(AuthState.ONLINE, "外网可达，无需认证")
            return AuthResult(AuthState.PENDING, "等待网关签发认证会话")

        # 1) 取当前节点
        node = self.get_current_node(session_id)
        node_path = str(node.get("currentNodePath", ""))
        if node_path:
            self._log(f"当前认证节点: {node_path}")

        # 2) 提交账号密码
        submitted = self.submit_credentials(session_id, credentials)
        if not submitted["ok"]:
            return self._classify(submitted["body"], submitted["message"])

        # 3) 若指定了服务则确认服务
        if credentials.service:
            services = self.list_services(session_id)
            if credentials.service in services:
                chosen = self.set_service(session_id, credentials.service)
                if not chosen["ok"]:
                    # 服务确认失败可能只是已在线，复核后再定
                    pass

        # 4) 复核在线
        if self.check_online(session_id):
            return AuthResult(AuthState.ONLINE, "连网成功")
        return AuthResult(AuthState.PENDING, "已提交认证，在线状态待确认", detail=submitted.get("body", {}))

    def _authenticate_simple(self, credentials: Credentials, session_id: str | None) -> AuthResult:
        """通用登录：把账号密码直接 POST 到登录接口，再复核联网状态。"""
        # 已能上外网则无需认证
        if self._internet_ok():
            return AuthResult(AuthState.ONLINE, "外网可达，无需认证")

        config = self.profile.simple_login
        login_path = config.get("login_path") or self.profile.endpoint("service_login")
        if not login_path:
            return AuthResult(AuthState.ERROR, "未配置登录接口路径（simple_login.login_path）")

        payload = {
            config.get("username_field", "username"): credentials.username,
            config.get("password_field", "password"): credentials.password,
        }
        payload.update(config.get("extra_fields", {}) or {})
        if session_id:
            payload.setdefault(self.profile.session_field, session_id)

        method = (config.get("method") or "POST").upper()
        if method == "GET":
            status, body = self._get(login_path, query=payload)
        else:
            status, body = self._post(login_path, payload)

        if status != 200 or not self._ok(body):
            message = str(body.get("message") or f"HTTP {status}")
            return self._classify(body, message)

        # 登录后复核：优先门户在线接口（若配了 sessionId 与在线接口），否则用外网探测
        if session_id and self.profile.endpoint("online_info") and self.check_online(session_id):
            return AuthResult(AuthState.ONLINE, "连网成功")
        if self._internet_ok():
            return AuthResult(AuthState.ONLINE, "连网成功")
        return AuthResult(AuthState.PENDING, "已提交登录，联网状态待确认", detail=body)

    def _classify(self, body: dict, message: str) -> AuthResult:
        category = self.profile.classify_error(message)
        if category in ("password_wrong", "account_invalid", "terminal_limit", "auth_fail"):
            return AuthResult(AuthState.ERROR, message, detail={"category": category})
        if category == "session_expired":
            return AuthResult(AuthState.PENDING, "会话已过期，等待重新签发", detail={"category": category})
        return AuthResult(AuthState.OFFLINE, message, detail=body)

    def _internet_ok(self) -> bool:
        for host in self.profile.probe_hosts:
            if https_reachable(host, adapter=self.adapter, timeout=5, port=self.profile.probe_port):
                return True
        return False

    def _log(self, message: str) -> None:
        pass  # 预留：CLI 可注入日志回调
