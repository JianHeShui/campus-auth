"""认证客户端测试：用本地模拟门户（复刻工作流契约）验证流程，不触网。"""
import atexit
import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from campus_auth.client import Client, Credentials
from campus_auth.network import NetworkAdapter
from campus_auth.portal import load_profile
from campus_auth.state import AuthState

# 临时文件用系统临时目录：测试不依赖仓库可写（只读环境也能跑）
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="campus-auth-test-"))
atexit.register(shutil.rmtree, _TMP_ROOT, True)

# 日志隔离：认证链路会写 ~/.campus-auth/auth-debug.log，测试统一重定向到临时目录，
# 避免每次跑测试污染开发者真实日志、也避免依赖本机状态。
_LOG_PATH_PATCH = None


def setUpModule():
    global _LOG_PATH_PATCH
    _LOG_PATH_PATCH = patch("campus_auth.logutil.LOG_PATH", _TMP_ROOT / "auth-debug.log")
    _LOG_PATH_PATCH.start()


def tearDownModule():
    if _LOG_PATH_PATCH is not None:
        _LOG_PATH_PATCH.stop()


class FakePortalHandler(BaseHTTPRequestHandler):
    """复刻认证工作流契约（本地模拟门户，不触网）。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静默
        pass

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/eportal/adaptor/getOnlineUserInfo":
            if self.server.online:
                self._send(200, {"code": 200, "data": {"portalOnlineUserInfo": {"result": "success"}}})
            else:
                self._send(200, {"code": 200, "data": {"portalOnlineUserInfo": {"result": "fail", "message": "dx.failed.user.offline"}}})
            return
        self._send(404, {})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._read_body()
        if path == "/eportal/workFlow/getCurrentNode":
            self._send(200, {"code": 200, "data": {"currentNodePath": "prod_auth", "userId": "u1"}})
            return
        if path == "/eportal/workFlow/updateUserSession":
            self.server.login_payload = body
            data = body.get("updateSessionData") or {}
            if data.get("userPwd") == "wrong":
                self._send(200, {"code": 400, "message": "账号或密码错误"})
            else:
                self.server.online = True
                self._send(200, {"code": 200, "message": "ok"})
            return
        if path == "/eportal/network/serviceSelection":
            self._send(200, {"code": 200, "data": {"services": ["中国移动", "中国联通", "校园网"]}})
            return
        if path == "/eportal/network/setService":
            self.server.service_payload = body
            self._send(200, {"code": 200, "data": {"switchResult": "success", "message": "ok"}})
            return
        self._send(404, {})


def make_profile(port: int):
    file = _TMP_ROOT / "test_portal.json"
    file.write_text(json.dumps({
        "portal": {"host": "127.0.0.1", "port": port},
        "endpoints": {
            "online_info": "/eportal/adaptor/getOnlineUserInfo",
            "service_selection": "/eportal/network/serviceSelection",
            "set_service": "/eportal/network/setService",
            "get_current_node": "/eportal/workFlow/getCurrentNode",
            "update_session": "/eportal/workFlow/updateUserSession",
        },
        "session": {"mode": "manual", "field_name": "sessionId", "flow_key": "portal_auth"},
        "workflow": {
            "auth_type": "account",
            "result_value": "success",
            "credential_fields": {"username": "userName", "password": "userPwd", "auth_type": "authType"},
            "service_fields": {"session_id": "sessionId", "service": "serviceName"},
        },
        "online_check": {"path_field": "data.portalOnlineUserInfo.result", "success_value": "success"},
    }), encoding="utf-8")
    return load_profile(file)


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePortalHandler)
        cls.server.online = False
        cls.server.login_payload = None
        cls.server.service_payload = None
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.profile = make_profile(cls.port)
        cls.adapter = NetworkAdapter(12, "以太网", "10.0.0.2", "00:00:00:00:00:00", (), "ethernet")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def make_client(self) -> Client:
        # 单元测试针对 127.0.0.1 的假门户，不做真实网卡源地址绑定
        return Client(self.profile, adapter=None, timeout=5)

    def test_check_online_true_when_result_success(self):
        client = self.make_client()
        self.server.online = True
        self.assertTrue(client.check_online("abc"))

    def test_check_online_false_when_result_fail(self):
        client = self.make_client()
        self.server.online = False
        self.assertFalse(client.check_online("abc"))

    def test_get_current_node(self):
        client = self.make_client()
        node = client.get_current_node("abc")
        self.assertEqual(node.get("currentNodePath"), "prod_auth")

    def test_submit_credentials_fields(self):
        client = self.make_client()
        self.server.online = False
        result = client.submit_credentials("abc", Credentials("alice", "secret", ""))
        self.assertTrue(result["ok"])
        payload = self.server.login_payload
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["sessionId"], "abc")
        self.assertEqual(payload["updateSessionData"]["userName"], "alice")
        self.assertEqual(payload["updateSessionData"]["userPwd"], "secret")
        self.assertEqual(payload["updateSessionData"]["authType"], "account")

    def test_authenticate_full_flow(self):
        client = self.make_client()
        self.server.online = False
        result = client.authenticate(Credentials("alice", "secret", "中国移动"), session_id="abc")
        self.assertEqual(result.state, AuthState.ONLINE)
        self.assertEqual(self.server.login_payload["updateSessionData"]["userName"], "alice")
        self.assertEqual(self.server.service_payload["serviceName"], "中国移动")

    def test_authenticate_wrong_password_is_error(self):
        client = self.make_client()
        self.server.online = False
        result = client.authenticate(Credentials("alice", "wrong", ""), session_id="abc")
        self.assertEqual(result.state, AuthState.ERROR)

    def test_redact_hides_credentials(self):
        creds = Credentials("alice", "secret", "")
        self.assertNotIn("secret", creds.redact("错误 secret 和 alice"))
        self.assertIn("[已隐藏]", creds.redact("错误 secret"))


class CasDispatchTests(unittest.TestCase):
    """CAS 模式状态分派：CAS 登录成功 ≠ 已上线；工作流失败时应 PENDING 并带真实原因。"""

    @staticmethod
    def _client() -> Client:
        file = _TMP_ROOT / "cas_profile.json"
        file.write_text(json.dumps({"auth_mode": "cas"}), encoding="utf-8")
        return Client(load_profile(file), adapter=None, timeout=5)

    def test_workflow_confirmed_and_internet_ok_is_online(self):
        client = self._client()
        cas_result = {"ok": True, "message": "认证成功（已上线）",
                      "detail": {"online_confirmed": True}}
        with patch.object(client, "_internet_ok", side_effect=[False, True]), \
             patch("campus_auth.cas.authenticate_cas", return_value=cas_result):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.ONLINE)

    def test_workflow_failed_keeps_pending_with_reason(self):
        client = self._client()
        cas_result = {
            "ok": True,
            "message": "CAS 认证成功（上线状态待确认）",
            "detail": {"online_confirmed": False, "workflow_error": "工作流 userOnline 未上线"},
        }
        with patch.object(client, "_internet_ok", side_effect=[False, False]), \
             patch("campus_auth.cas.authenticate_cas", return_value=cas_result):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.PENDING)
        self.assertIn("工作流上线未确认", result.message)
        self.assertIn("userOnline", result.message)

    def test_confirmed_but_internet_unreachable_is_pending(self):
        client = self._client()
        cas_result = {"ok": True, "message": "认证成功（已上线）",
                      "detail": {"online_confirmed": True}}
        with patch.object(client, "_internet_ok", side_effect=[False, False]), \
             patch("campus_auth.cas.authenticate_cas", return_value=cas_result):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.PENDING)

    def test_wrong_password_is_error(self):
        client = self._client()
        cas_result = {"ok": False, "message": "CAS 登录失败 (HTTP 200)",
                      "detail": {"body": "用户不存在或者密码错误"}}
        with patch.object(client, "_internet_ok", return_value=False), \
             patch("campus_auth.cas.authenticate_cas", return_value=cas_result):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.ERROR)
        self.assertIn("密码", result.message)

    def test_network_error_becomes_pending(self):
        client = self._client()
        cas_result = {"ok": False, "message": "captive探测失败: 连接超时", "detail": {}}
        with patch.object(client, "_internet_ok", return_value=False), \
             patch("campus_auth.cas.authenticate_cas", return_value=cas_result):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.PENDING)


class ClientHelpersTests(unittest.TestCase):
    def test_ok_accepts_string_code(self):
        client = Client(load_profile(_TMP_ROOT / "no-such-profile.json"), adapter=None)
        self.assertTrue(client._ok({"code": "200"}))
        self.assertTrue(client._ok({}))
        self.assertFalse(client._ok({"code": 400}))

    def test_is_online_delegates_to_internet_probe(self):
        client = Client(load_profile(_TMP_ROOT / "no-such-profile.json"), adapter=None)
        with patch.object(client, "_internet_ok", return_value=True) as inner:
            self.assertTrue(client.is_online())
        inner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
