"""CAS SSO 认证测试：HTML 元素提取、参数解析、cookie 累积、工作流判定。"""
import unittest
from unittest.mock import MagicMock

from campus_auth.cas import (
    _build_login_url,
    _CookieJar,
    _extract_element,
    _param,
    _parse_set_cookie,
    _summarize,
    _workflow_step_ok,
)


class BuildLoginUrlTests(unittest.TestCase):
    """HTTPS CAS 门户必须按画像 scheme 构造登录 URL（不能写死 http）。"""

    def test_http_scheme(self):
        url = _build_login_url("http", "10.0.0.1", 80, "fs", "cp", "nas", "uip")
        self.assertTrue(url.startswith("http://10.0.0.1:80/cas-sso/login?"))
        self.assertIn("flowSessionId=fs", url)

    def test_https_scheme(self):
        url = _build_login_url("https", "portal.x.edu.cn", 8443, "fs", "cp", "nas", "uip")
        self.assertTrue(url.startswith("https://portal.x.edu.cn:8443/cas-sso/login?"))
        self.assertIn("timer=", url)


class ExtractElementTests(unittest.TestCase):
    def test_inner_text(self):
        html = '<div id="login-croypto">Qvy2L55c2aTCHUc6uX/Llw==</div>'
        self.assertEqual(_extract_element(html, "login-croypto"), "Qvy2L55c2aTCHUc6uX/Llw==")

    def test_value_attr(self):
        html = '<input id="login-page-flowkey" value="abc-123">'
        self.assertEqual(_extract_element(html, "login-page-flowkey"), "abc-123")

    def test_missing(self):
        self.assertIsNone(_extract_element("<html></html>", "login-croypto"))


class ParamTests(unittest.TestCase):
    def test_url_query(self):
        url = "http://x/cas-sso/login?flowSessionId=abc&customPageId=def"
        self.assertEqual(_param(url, "flowSessionId"), "abc")
        self.assertEqual(_param(url, "customPageId"), "def")

    def test_text_kv(self):
        self.assertEqual(_param('flowSessionId="xyz"', "flowSessionId"), "xyz")

    def test_missing(self):
        self.assertEqual(_param("http://x/login", "flowSessionId"), "")


class SetCookieTests(unittest.TestCase):
    def test_multiple_cookies_all_kept(self):
        """门户同时下发多个 Set-Cookie 时必须全部保留（只取第一个会丢会话）。"""
        headers = [
            ("Content-Type", "text/html"),
            ("Set-Cookie", "SESSION=abc123; Path=/; HttpOnly"),
            ("Set-Cookie", "JSESSIONID=xyz789; Secure; HttpOnly"),
        ]
        self.assertEqual(_parse_set_cookie(headers),
                         {"SESSION": "abc123", "JSESSIONID": "xyz789"})

    def test_attributes_stripped(self):
        self.assertEqual(_parse_set_cookie([("Set-Cookie", "A=1; Path=/; Domain=x")]), {"A": "1"})

    def test_ignores_non_cookie_and_invalid(self):
        headers = [("Set-Cookie", "no-equals-sign"), ("Content-Length", "10"), ("Set-Cookie", "=empty")]
        self.assertEqual(_parse_set_cookie(headers), {})


class CookieJarTests(unittest.TestCase):
    @staticmethod
    def _response(headers):
        resp = MagicMock()
        resp.getheaders.return_value = headers
        return resp

    def test_accumulates_across_responses(self):
        jar = _CookieJar()
        self.assertFalse(jar)
        jar.update(self._response([("Set-Cookie", "A=1; Path=/")]))
        jar.update(self._response([("Set-Cookie", "B=2; Path=/")]))
        self.assertTrue(jar)
        self.assertEqual(jar.header(), "A=1; B=2")
        self.assertEqual(sorted(jar.names()), ["A", "B"])

    def test_later_value_overrides(self):
        jar = _CookieJar()
        jar.update(self._response([("Set-Cookie", "A=1")]))
        jar.update(self._response([("Set-Cookie", "A=2")]))
        self.assertEqual(jar.header(), "A=2")

    def test_bad_response_is_silent(self):
        jar = _CookieJar()
        bad = MagicMock()
        bad.getheaders.side_effect = RuntimeError("boom")
        jar.update(bad)
        self.assertFalse(jar)


class WorkflowStepOkTests(unittest.TestCase):
    def test_http_200_with_code_200(self):
        self.assertEqual(_workflow_step_ok(200, {"code": 200}), (True, ""))

    def test_missing_code_is_ok(self):
        self.assertEqual(_workflow_step_ok(200, {"data": {}}), (True, ""))

    def test_string_code_200_is_ok(self):
        self.assertEqual(_workflow_step_ok(200, {"code": "200"}), (True, ""))

    def test_http_error(self):
        ok, message = _workflow_step_ok(500, {})
        self.assertFalse(ok)
        self.assertIn("500", message)

    def test_business_error_uses_message(self):
        ok, message = _workflow_step_ok(200, {"code": 400, "message": "认证失败"})
        self.assertFalse(ok)
        self.assertEqual(message, "认证失败")

    def test_business_error_without_message(self):
        ok, message = _workflow_step_ok(200, {"code": 400})
        self.assertFalse(ok)
        self.assertIn("400", message)


class SummarizeTests(unittest.TestCase):
    def test_dict_to_json(self):
        self.assertEqual(_summarize({"online": True}), '{"online": true}')

    def test_truncates(self):
        self.assertLessEqual(len(_summarize("x" * 500)), 160)


if __name__ == "__main__":
    unittest.main()
