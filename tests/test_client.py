"""认证客户端测试：用本地模拟门户（复刻工作流契约）验证流程，不触网。"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from campus_auth.client import Client, Credentials
from campus_auth.network import NetworkAdapter
from campus_auth.portal import load_profile
from campus_auth.state import AuthState

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
_TMP_ROOT.mkdir(exist_ok=True)


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


if __name__ == "__main__":
    unittest.main()
