"""通用登录（simple 模式）测试：本地假门户 + mock 外网探测，不触网。"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from campus_auth.client import Client, Credentials
from campus_auth.portal import load_profile
from campus_auth.state import AuthState

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
_TMP_ROOT.mkdir(exist_ok=True)


class SimplePortalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if path == "/login":
            self.server.login_payload = body
            if body.get("password") == "wrong":
                self._send(200, {"code": 400, "message": "账号或密码错误"})
            else:
                self.server.online = True
                self._send(200, {"code": 200, "message": "ok"})
            return
        self._send(404, {})

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_simple_profile(port: int):
    file = _TMP_ROOT / "simple_portal.json"
    file.write_text(json.dumps({
        "auth_mode": "simple",
        "portal": {"host": "127.0.0.1", "port": port, "scheme": "http", "entry_path": "/"},
        "simple_login": {
            "login_path": "/login",
            "method": "POST",
            "username_field": "username",
            "password_field": "password",
        },
        "connectivity": {"probe_hosts": [], "probe_port": 443},
    }), encoding="utf-8")
    return load_profile(file)


class SimpleLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SimplePortalHandler)
        cls.server.online = False
        cls.server.login_payload = None
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.profile = make_simple_profile(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def make_client(self) -> Client:
        return Client(self.profile, adapter=None, timeout=5)

    def test_simple_login_success_and_fields(self):
        client = self.make_client()
        self.server.online = False
        # 登录前外网不可达，登录后可达
        with patch.object(client, "_internet_ok", side_effect=[False, True]):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.ONLINE)
        payload = self.server.login_payload
        self.assertEqual(payload["username"], "alice")
        self.assertEqual(payload["password"], "secret")

    def test_simple_login_wrong_password_is_error(self):
        client = self.make_client()
        self.server.online = False
        with patch.object(client, "_internet_ok", return_value=False):
            result = client.authenticate(Credentials("alice", "wrong", ""))
        self.assertEqual(result.state, AuthState.ERROR)

    def test_simple_login_skips_when_already_online(self):
        client = self.make_client()
        self.server.online = False
        self.server.login_payload = None
        with patch.object(client, "_internet_ok", return_value=True):
            result = client.authenticate(Credentials("alice", "secret", ""))
        self.assertEqual(result.state, AuthState.ONLINE)
        self.assertIsNone(self.server.login_payload)  # 未提交登录


if __name__ == "__main__":
    unittest.main()
