"""门户类型探测测试：mock 特征响应，验证分类逻辑（不触网）。"""
import unittest
from unittest.mock import patch

from campus_auth.detect import parse_address, probe_portal


def _fake_get(responses: dict[str, tuple]):
    """构造一个按路径返回响应的 _get 替身。"""
    def fake(host, port, scheme, path, timeout=6):
        for key, result in responses.items():
            if path == key or path.startswith(key):
                return result
        return (None, {}, "")
    return fake


class ParseAddressTests(unittest.TestCase):
    def test_plain_ip(self):
        self.assertEqual(parse_address("10.0.0.1"), ("10.0.0.1", 80, "http"))

    def test_host_with_port(self):
        self.assertEqual(parse_address("portal.x.edu.cn:8080"), ("portal.x.edu.cn", 8080, "http"))

    def test_https(self):
        self.assertEqual(parse_address("https://portal.x.edu.cn:8443"), ("portal.x.edu.cn", 8443, "https"))


class DetectTests(unittest.TestCase):
    def test_ruijie_detected_by_config(self):
        get = _fake_get({"/portal/assets/config.js": (200, {}, "锐捷网络 smpdomain enableCompliance")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertTrue(result["recognized"])
        self.assertEqual(result["type"], "锐捷 SAM+")
        self.assertEqual(result["mode"], "workflow")

    def test_ruijie_detected_by_sso_marker(self):
        get = _fake_get({"/portal/": (200, {}, "<base href='/portal/'> __PLATFORM_SSO__ = 'cas-sso'")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "锐捷 SAM+")

    def test_srun_detected(self):
        get = _fake_get({"/eportal/index.jsp": (200, {}, "wlanuserip=1.2.3.4 wlanacname=xxx")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "深澜 Srun")

    def test_drcom_detected(self):
        get = _fake_get({"/": (200, {}, "Welcome to Dr.COM web portal")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "Dr.COM")

    def test_huawei_detected(self):
        get = _fake_get({"/": (200, {}, "Huawei Agile Controller")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "华为")

    def test_session_guard_fallback(self):
        get = _fake_get({"/eportal/adaptor/getOnlineUserInfo": (500, {}, "Required request parameter 'sessionId'")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertTrue(result["recognized"])
        self.assertIn("ePortal", result["type"])

    def test_generic_fallback(self):
        get = _fake_get({})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertFalse(result["recognized"])
        self.assertEqual(result["mode"], "simple")


if __name__ == "__main__":
    unittest.main()
