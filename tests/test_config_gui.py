"""配置界面纯函数测试：端口校验、地址解析与「地址框 → 画像」往返（不创建窗口）。"""
import unittest

from campus_auth.config_gui import (
    ConfigWindow,
    _apply_address,
    _format_address,
    _parse_address,
)


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


class AddressRoundTripTests(unittest.TestCase):
    """P0 回归：HTTPS / 非 80 端口配置经「打开→保存」必须原样保留（单一数据源）。"""

    PROFILES = (
        {"host": "10.0.0.1", "port": 80, "scheme": "http"},
        {"host": "portal.x.edu.cn", "port": 443, "scheme": "https"},
        {"host": "10.0.0.1", "port": 8080, "scheme": "http"},
        {"host": "portal.x.edu.cn", "port": 8443, "scheme": "https"},
    )

    def test_format_omits_default_port(self):
        self.assertEqual(_format_address({"portal": self.PROFILES[0]}), "http://10.0.0.1")
        self.assertEqual(_format_address({"portal": self.PROFILES[1]}), "https://portal.x.edu.cn")

    def test_format_keeps_non_default_port(self):
        self.assertEqual(_format_address({"portal": self.PROFILES[2]}), "http://10.0.0.1:8080")
        self.assertEqual(_format_address({"portal": self.PROFILES[3]}), "https://portal.x.edu.cn:8443")

    def test_format_missing_portal(self):
        self.assertEqual(_format_address({}), "")
        self.assertEqual(_format_address({"portal": None}), "")
        self.assertEqual(_format_address({"portal": {"host": ""}}), "")

    def test_round_trip_preserves_scheme_and_port(self):
        """_format_address → _apply_address 必须等于原始 portal。"""
        for portal in self.PROFILES:
            with self.subTest(portal=portal):
                text = _format_address({"portal": portal})
                data = {"portal": {}}
                _apply_address(data, text)
                self.assertEqual(data["portal"], portal)

    def test_apply_empty_address_rejected(self):
        with self.assertRaises(ValueError):
            _apply_address({"portal": {}}, "")

    def test_apply_invalid_port_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            _apply_address({"portal": {}}, "10.0.0.1:99999")
        self.assertIn("门户地址", str(ctx.exception))

    def test_apply_plain_host(self):
        data = {"portal": {}}
        _apply_address(data, "10.0.0.1")
        self.assertEqual(data["portal"], {"host": "10.0.0.1", "port": 80, "scheme": "http"})


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
