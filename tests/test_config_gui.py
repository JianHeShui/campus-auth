"""配置界面纯函数测试：端口校验、地址解析与「地址框 → 画像」往返（不创建窗口）。"""
import json
import unittest

from campus_auth.config_gui import (
    _FIELD_LABELS,
    ConfigWindow,
    _apply_address,
    _autostart_hint,
    _format_address,
    _parse_address,
    _parse_seconds,
)
from campus_auth.portal import DEFAULT_PROFILE


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


class ParseSecondsTests(unittest.TestCase):
    """自动保护间隔：必须是 5-3600 的整数秒（范围与 cli.py 保持一致）。"""

    def test_valid_values(self):
        for value, expected in (("5", 5), ("60", 60), ("300", 300), ("3600", 3600)):
            with self.subTest(value=value):
                self.assertEqual(_parse_seconds(value, "在线复核间隔"), expected)

    def test_strip_whitespace(self):
        self.assertEqual(_parse_seconds("  60  ", "在线复核间隔"), 60)
        self.assertEqual(_parse_seconds("\t300\n", "失败重试上限"), 300)

    def test_non_integer_rejected(self):
        for value in ("", " ", "abc", "60.5", "1e2", "60秒"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_seconds(value, "在线复核间隔")

    def test_negative_rejected(self):
        for value in ("-1", "-300"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_seconds(value, "在线复核间隔")

    def test_out_of_range_rejected(self):
        for value in ("0", "4", "3601", "9999"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_seconds(value, "在线复核间隔")

    def test_error_message_contains_label(self):
        for value in ("bad", "0", "3601"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    _parse_seconds(value, "失败重试上限")
                self.assertIn("失败重试上限", str(ctx.exception))


class _StubVar:
    """最小 StringVar 替身：_collect 只调用 .get()，无需创建真实 Tk 控件。"""

    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value


class WatchCollectTests(unittest.TestCase):
    """_collect：watch 间隔字段走 _parse_seconds 转 int，其余字段逻辑不变。"""

    @staticmethod
    def _window(**values: str) -> ConfigWindow:
        window = ConfigWindow.__new__(ConfigWindow)  # 绕过 __init__，避免创建 Tk 窗口
        window.vars = {key: _StubVar(value) for key, value in values.items()}
        window.mode_var = _StubVar("workflow")
        window.address_var = None
        window.extra_fields_text = None
        window.error_markers_text = None
        return window

    def test_watch_fields_are_ints(self):
        window = self._window(**{
            "watch.recheck_interval": "120",
            "watch.max_interval": "300",
        })
        data = window._collect()
        self.assertEqual(data["watch"]["recheck_interval"], 120)
        self.assertEqual(data["watch"]["max_interval"], 300)
        # GUI 不暴露 network_events：保存时必须保留默认 True
        self.assertTrue(data["watch"]["network_events"])

    def test_invalid_watch_value_rejected(self):
        for key in ("watch.recheck_interval", "watch.max_interval"):
            with self.subTest(key=key):
                window = self._window(**{key: "0"})
                with self.assertRaises(ValueError) as ctx:
                    window._collect()
                self.assertIn(_FIELD_LABELS[key], str(ctx.exception))

    def test_network_events_false_is_preserved(self):
        """用户手改 portal.json 关闭 network_events 后，GUI 保存不应重置为 true。"""
        window = self._window(**{
            "watch.recheck_interval": "60",
            "watch.max_interval": "300",
        })
        loaded = json.loads(json.dumps(DEFAULT_PROFILE))
        loaded["watch"]["network_events"] = False
        window._loaded_data = loaded
        data = window._collect()
        self.assertFalse(data["watch"]["network_events"])
        self.assertEqual(data["watch"]["recheck_interval"], 60)

    def test_loaded_login_section_preserved(self):
        """表单未展开的 login 段在保存时必须保留，不被默认值覆盖。"""
        window = self._window(**{
            "watch.recheck_interval": "60",
            "watch.max_interval": "300",
        })
        loaded = json.loads(json.dumps(DEFAULT_PROFILE))
        loaded["login"]["path"] = "/eportal/portal/login"
        loaded["login"]["callback"] = "dr1003"
        window._loaded_data = loaded
        data = window._collect()
        self.assertEqual(data["login"]["path"], "/eportal/portal/login")
        self.assertEqual(data["login"]["callback"], "dr1003")


class FieldLabelTests(unittest.TestCase):
    def test_watch_labels_present(self):
        for key in ("watch.recheck_interval", "watch.max_interval"):
            with self.subTest(key=key):
                self.assertIn(key, _FIELD_LABELS)


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


class AutostartHintTests(unittest.TestCase):
    """启动成功弹窗中的开机自启说明：必须区分「一直运行」与「仅本次运行」。"""

    def test_enabled_mentions_always_on(self):
        hint = _autostart_hint(True)
        self.assertIn("已开启", hint)
        self.assertIn("开机后自动运行", hint)

    def test_disabled_mentions_this_run_only(self):
        hint = _autostart_hint(False)
        self.assertIn("未开启", hint)
        self.assertIn("仅本次运行", hint)


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
