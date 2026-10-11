"""门户画像：把门户的可变部分（地址、接口、字段名、错误文案）数据化。

设计意图：认证逻辑与具体门户解耦。换校区/换学校时只需改 portal.json，
不改代码。画像内容全部来自黑盒探测。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PROFILE: dict[str, Any] = {
    # 认证引擎模式："workflow"（锐捷工作流）| "simple"（通用直接登录）
    "auth_mode": "workflow",
    "portal": {
        "host": "10.0.0.1",
        "port": 80,
        "scheme": "http",
        "entry_path": "/portal/entry/pc/authenticate;flowParams=undefined;from=",
    },
    "endpoints": {
        "query_terminal": "/eportal/adaptor/queryTerminalInfo",
        "online_info": "/eportal/adaptor/getOnlineUserInfo",
        "service_selection": "/eportal/network/serviceSelection",
        "service_login": "/eportal/network/serviceLogin",
        "operator_login": "/eportal/network/operatorLogin",
        "set_service": "/eportal/network/setService",
        "get_current_node": "/eportal/workFlow/getCurrentNode",
        "update_session": "/eportal/workFlow/updateUserSession",
    },
    "session": {
        "mode": "captive",
        "field_name": "sessionId",
        "flow_key": "portal_auth",
        "redirect_probe_url": "http://www.baidu.com/",
    },
    # 工作流登录：账号密码经 updateUserSession 的 updateSessionData 提交
    "workflow": {
        "auth_type": "account",  # 账号密码认证的 authType 值（待离线确认真实枚举）
        "result_value": "success",
        "credential_fields": {"username": "userName", "password": "userPwd", "auth_type": "authType"},
        "service_fields": {"session_id": "sessionId", "service": "serviceName"},
    },
    # 通用登录：直接把账号密码 POST 到登录接口（非锐捷门户的兜底）
    "simple_login": {
        "login_path": "",
        "method": "POST",
        "username_field": "username",
        "password_field": "password",
        "extra_fields": {},
    },
    "online_check": {"path_field": "data.portalOnlineUserInfo.result", "success_value": "success"},
    "error_markers": {
        "auth_fail": ["认证失败", "auth.fail"],
        "account_invalid": ["上网账号已失效", "ACCOUNT_BINDING_INVALID"],
        "terminal_limit": ["上网终端数已达上限", "EXCEED_LIMIT"],
        "password_wrong": ["账号或密码", "密码不正确", "密码错误"],
        "session_expired": ["请重新连网认证", "sessionId"],
    },
    "connectivity": {"probe_hosts": ["www.baidu.com", "www.qq.com"], "probe_port": 443},
}


class ProfileError(RuntimeError):
    """画像文件缺失或非法。"""


@dataclass(frozen=True)
class PortalProfile:
    host: str
    port: int
    scheme: str
    entry_path: str
    endpoints: dict[str, str]
    session_field: str
    session_mode: str
    flow_key: str
    redirect_probe_url: str
    online_path_field: str
    online_success_value: str
    error_markers: dict[str, list[str]] = field(default_factory=dict)
    probe_hosts: tuple[str, ...] = ("www.baidu.com", "www.qq.com")
    probe_port: int = 443
    # 认证引擎模式
    auth_mode: str = "workflow"
    # 工作流登录参数
    auth_type: str = "account"
    result_value: str = "success"
    credential_fields: dict[str, str] = field(default_factory=lambda: {"username": "userName", "password": "userPwd", "auth_type": "authType"})
    service_fields: dict[str, str] = field(default_factory=lambda: {"session_id": "sessionId", "service": "serviceName"})
    # 通用登录参数
    simple_login: dict[str, Any] = field(default_factory=lambda: {
        "login_path": "", "method": "POST",
        "username_field": "username", "password_field": "password",
        "extra_fields": {},
    })

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def endpoint(self, name: str) -> str:
        return self.endpoints.get(name, "")

    def classify_error(self, message: str) -> str | None:
        """按画像的错误文案把失败归类，返回类别名或 None。"""
        for category, markers in self.error_markers.items():
            for marker in markers:
                if marker in message:
                    return category
        return None


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict，override 优先。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_profile(path: str | Path | None) -> PortalProfile:
    """加载画像：默认值 ← portal.json（若存在）。"""
    data: dict[str, Any] = DEFAULT_PROFILE
    if path is not None:
        file = Path(path)
        if file.exists():
            try:
                user = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ProfileError(f"portal.json 无法解析: {exc}") from exc
            data = deep_merge(data, user)

    portal = data["portal"]
    endpoints = data["endpoints"]
    session = data["session"]
    workflow = data.get("workflow", {})
    credential_fields = workflow.get("credential_fields", {"username": "userName", "password": "userPwd", "auth_type": "authType"})
    service_fields = workflow.get("service_fields", {"session_id": "sessionId", "service": "serviceName"})
    simple_login = data.get("simple_login", {})
    online = data["online_check"]
    conn = data.get("connectivity", {})

    return PortalProfile(
        host=portal["host"],
        port=int(portal["port"]),
        scheme=portal["scheme"],
        entry_path=portal["entry_path"],
        endpoints=endpoints,
        session_field=session["field_name"],
        session_mode=session.get("mode", "captive"),
        flow_key=session.get("flow_key", "portal_auth"),
        redirect_probe_url=session.get("redirect_probe_url", "http://www.baidu.com/"),
        online_path_field=online["path_field"],
        online_success_value=online["success_value"],
        error_markers=data.get("error_markers", {}),
        probe_hosts=tuple(conn.get("probe_hosts", ["www.baidu.com", "www.qq.com"])),
        probe_port=int(conn.get("probe_port", 443)),
        auth_mode=data.get("auth_mode", "workflow"),
        auth_type=workflow.get("auth_type", "account"),
        result_value=workflow.get("result_value", "success"),
        credential_fields=credential_fields,
        service_fields=service_fields,
        simple_login=simple_login,
    )
