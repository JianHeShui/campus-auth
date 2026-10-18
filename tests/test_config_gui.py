"""配置界面纯函数测试：端口校验与地址解析（不创建窗口）。"""
import unittest

from campus_auth.config_gui import ConfigWindow, _parse_address


class ParsePortTests(unittest.TestCase):
    def test_valid_port(self):
        self.assertEqual(ConfigWindow._parse_port("80", "端口"), 80)
        self.assertEqual(ConfigWindow._parse_port("8080", "端口"), 8080)
        self.assertEqual(ConfigWindow._parse_port("65535", "端口"), 65535)

    def test_non_numeric_rejected(self):
        for value in ("", "abc", "80.5", " "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ConfigWindow._parse_port(value, "端口")

    def test_out_of_range_rejected(self):
        for value in ("0", "65536", "70000"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ConfigWindow._parse_port(value, "端口")

    def test_error_message_contains_label(self):
        with self.assertRaises(ValueError) as ctx:
            ConfigWindow._parse_port("bad", "外网探测端口")
        self.assertIn("外网探测端口", str(ctx.exception))


class ParseAddressTests(unittest.TestCase):
    def test_plain_host(self):
        self.assertEqual(_parse_address("10.0.0.1"), ("10.0.0.1", 80, "http"))

    def test_host_with_port(self):
        self.assertEqual(_parse_address("portal.x.edu.cn:8080"), ("portal.x.edu.cn", 8080, "http"))

    def test_https_with_port(self):
        self.assertEqual(_parse_address("https://portal.x.edu.cn:8443"),
                         ("portal.x.edu.cn", 8443, "https"))


class DetectConsistencyTests(unittest.TestCase):
    """「一键生成配置」的类型校验：自动探测结果与用户所选类型对比。"""

    def test_match(self):
        self.assertEqual(
            ConfigWindow._detect_consistency("锐捷 SAM+（工作流）", "锐捷 SAM+（工作流）"),
            "match")

    def test_mismatch(self):
        self.assertEqual(
            ConfigWindow._detect_consistency("锐捷 SAM+（工作流）", "华三 CAS SSO（加密）"),
            "mismatch")

    def test_unknown_when_detection_failed(self):
        self.assertEqual(ConfigWindow._detect_consistency("锐捷 SAM+（工作流）", None), "unknown")
        self.assertEqual(ConfigWindow._detect_consistency("锐捷 SAM+（工作流）", ""), "unknown")

    def test_custom_template_is_not_overridden(self):
        self.assertEqual(
            ConfigWindow._detect_consistency("自定义（手动填写）", "华三 CAS SSO（加密）"),
            "custom")

    def test_no_selection_treated_as_custom(self):
        self.assertEqual(ConfigWindow._detect_consistency(None, "华三 CAS SSO（加密）"), "custom")


if __name__ == "__main__":
    unittest.main()
