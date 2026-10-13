"""CAS SSO 认证测试：HTML 元素提取、参数解析、密码加密流程。"""
import unittest

from campus_auth.cas import _extract_element, _param


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


if __name__ == "__main__":
    unittest.main()
