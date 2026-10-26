"""画像加载与状态机单元测试。"""
import atexit
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from campus_auth.portal import DEFAULT_PROFILE, ProfileError, deep_merge, load_profile
from campus_auth.state import RetryPolicy

# 临时文件用系统临时目录：测试不依赖仓库可写（只读环境也能跑）
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="campus-auth-test-"))
atexit.register(shutil.rmtree, _TMP_ROOT, True)

# login 段骨架的全部字段（方案 §4.2）
_LOGIN_KEYS = (
    "path", "method", "callback", "user_field", "pass_field",
    "password_transform", "service_field", "service_suffix",
    "extra_params", "ip_field", "success", "failure",
)


def _isolated_profile_path() -> Path:
    """返回一个不存在的临时路径，用作"默认画像"的加载入口。

    load_profile(None) 会去项目根找真实的 portal.json，测试结果就会依赖本机配置；
    显式传不存在的临时路径，确保画像 100% 来自 DEFAULT_PROFILE，与开发机隔离。
    """
    return _TMP_ROOT / "no-such-portal.json"


def _write_profile(name: str, data: dict) -> Path:
    file = _TMP_ROOT / name
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return file


class DeepMergeTests(unittest.TestCase):
    def test_nested_override(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 9}}
        self.assertEqual(deep_merge(base, override), {"a": {"x": 1, "y": 9}, "b": 3})

    def test_new_key_added(self):
        self.assertEqual(deep_merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})


class ProfileTests(unittest.TestCase):
    def test_default_profile_loads(self):
        # 显式传临时路径：不读真实 portal.json，断言以 DEFAULT_PROFILE 为准
        profile = load_profile(_isolated_profile_path())
        self.assertEqual(profile.host, DEFAULT_PROFILE["portal"]["host"])
        self.assertEqual(profile.session_field, DEFAULT_PROFILE["session"]["field_name"])
        self.assertEqual(profile.auth_mode, DEFAULT_PROFILE["auth_mode"])

    def test_missing_profile_file_falls_back_to_defaults(self):
        profile = load_profile(_isolated_profile_path())
        self.assertEqual(profile.endpoints, DEFAULT_PROFILE["endpoints"])
        self.assertEqual(profile.entry_path, DEFAULT_PROFILE["portal"]["entry_path"])

    def test_custom_profile_overrides(self):
        file = _write_profile("custom_portal.json", {
            "portal": {"host": "10.0.0.1"},
            "workflow": {"credential_fields": {"username": "account"}},
        })
        try:
            profile = load_profile(file)
            self.assertEqual(profile.host, "10.0.0.1")
            self.assertEqual(profile.credential_fields["username"], "account")
            # 未覆盖的键保留默认值
            self.assertEqual(profile.credential_fields["password"], "userPwd")
        finally:
            file.unlink(missing_ok=True)

    def test_invalid_json_raises(self):
        file = _TMP_ROOT / "invalid_portal.json"
        file.write_text("{not json", encoding="utf-8")
        try:
            with self.assertRaises(ProfileError):
                load_profile(file)
        finally:
            file.unlink(missing_ok=True)

    def test_classify_error(self):
        profile = load_profile(_isolated_profile_path())
        self.assertEqual(profile.classify_error("账号或密码错误"), "password_wrong")
        self.assertEqual(profile.classify_error("请重新连网认证"), "session_expired")
        self.assertIsNone(profile.classify_error("未知信息"))


class LoginSectionTests(unittest.TestCase):
    """login 段骨架：默认值、覆盖解析、旧画像向后兼容（阶段 0 不参与认证分派）。"""

    def test_login_defaults_match_constant(self):
        profile = load_profile(_isolated_profile_path())
        self.assertEqual(profile.login, DEFAULT_PROFILE["login"])
        for key in _LOGIN_KEYS:
            self.assertIn(key, profile.login)

    def test_login_default_values(self):
        login = load_profile(_isolated_profile_path()).login
        self.assertEqual(login["path"], "")
        self.assertEqual(login["method"], "POST")
        self.assertEqual(login["password_transform"], "plain")
        self.assertEqual(login["service_suffix"], {})
        self.assertEqual(login["extra_params"], {})
        self.assertEqual(login["success"], {"contains": [], "jsonp": False})
        self.assertEqual(login["failure"], {"contains": []})

    def test_login_full_override_parsed(self):
        file = _write_profile("drcom_portal.json", {
            "auth_mode": "drcom",
            "login": {
                "path": "/eportal/portal/login",
                "method": "GET",
                "callback": "dr1003",
                "user_field": "user_account",
                "pass_field": "user_password",
                "password_transform": "base64",
                "service_field": "service_type",
                "service_suffix": {"中国移动": "@cmcc"},
                "extra_params": {"login_method": "1"},
                "ip_field": "wlan_user_ip",
                "success": {"contains": ["Portal协议认证成功"], "jsonp": True},
                "failure": {"contains": ["AC认证失败"]},
            },
        })
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        login = profile.login
        self.assertEqual(profile.auth_mode, "drcom")
        self.assertEqual(login["path"], "/eportal/portal/login")
        self.assertEqual(login["method"], "GET")
        self.assertEqual(login["callback"], "dr1003")
        self.assertEqual(login["user_field"], "user_account")
        self.assertEqual(login["pass_field"], "user_password")
        self.assertEqual(login["password_transform"], "base64")
        self.assertEqual(login["service_field"], "service_type")
        self.assertEqual(login["service_suffix"], {"中国移动": "@cmcc"})
        self.assertEqual(login["extra_params"], {"login_method": "1"})
        self.assertEqual(login["ip_field"], "wlan_user_ip")
        self.assertEqual(login["success"]["contains"], ["Portal协议认证成功"])
        self.assertTrue(login["success"]["jsonp"])
        self.assertEqual(login["failure"]["contains"], ["AC认证失败"])

    def test_login_partial_override_keeps_other_defaults(self):
        """局部覆盖时深度合并：未写的键沿用默认，不会丢字段。"""
        file = _write_profile("partial_login_portal.json", {
            "login": {"path": "/portal/login", "method": "GET"},
        })
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        login = profile.login
        self.assertEqual(login["path"], "/portal/login")
        self.assertEqual(login["method"], "GET")
        self.assertEqual(login["password_transform"], "plain")
        self.assertEqual(login["user_field"], "username")
        self.assertEqual(login["success"], {"contains": [], "jsonp": False})

    def test_nested_success_partial_override(self):
        """success 段局部覆盖：只改 jsonp，contains 默认值保留。"""
        file = _write_profile("jsonp_login_portal.json", {
            "login": {"success": {"jsonp": True}},
        })
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        self.assertTrue(profile.login["success"]["jsonp"])
        self.assertEqual(profile.login["success"]["contains"], [])

    def test_legacy_profile_without_login_section(self):
        """旧 portal.json 没有 login 段时仍能加载（向后兼容）。"""
        file = _write_profile("legacy_portal.json", {
            "portal": {"host": "10.0.0.2"},
            "simple_login": {"login_path": "/login"},
        })
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        self.assertEqual(profile.host, "10.0.0.2")
        self.assertEqual(profile.simple_login["login_path"], "/login")
        for key in _LOGIN_KEYS:
            self.assertIn(key, profile.login)


class WatchSectionTests(unittest.TestCase):
    """自动保护参数（watch 段）：默认值、覆盖解析、旧画像兼容（v0.3.2）。"""

    def test_watch_defaults(self):
        watch = load_profile(_isolated_profile_path()).watch
        self.assertEqual(watch["recheck_interval"], 60)
        self.assertEqual(watch["max_interval"], 300)
        self.assertTrue(watch["network_events"])

    def test_watch_overrides_parsed(self):
        file = _write_profile("watch_portal.json", {
            "watch": {"recheck_interval": 15, "max_interval": 120, "network_events": False},
        })
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        self.assertEqual(profile.watch["recheck_interval"], 15)
        self.assertEqual(profile.watch["max_interval"], 120)
        self.assertFalse(profile.watch["network_events"])

    def test_watch_partial_override_keeps_defaults(self):
        file = _write_profile("partial_watch_portal.json", {
            "watch": {"recheck_interval": 30},
        })
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        self.assertEqual(profile.watch["recheck_interval"], 30)
        self.assertEqual(profile.watch["max_interval"], 300)
        self.assertTrue(profile.watch["network_events"])

    def test_legacy_profile_without_watch_section(self):
        """旧 portal.json 没有 watch 段时仍能加载，并使用默认参数。"""
        file = _write_profile("legacy_watch_portal.json", {"portal": {"host": "10.0.0.2"}})
        try:
            profile = load_profile(file)
        finally:
            file.unlink(missing_ok=True)
        self.assertEqual(profile.watch, DEFAULT_PROFILE["watch"])


class RetryPolicyTests(unittest.TestCase):
    def test_backoff_sequence(self):
        policy = RetryPolicy()
        policy.on_failure(0)
        self.assertEqual(policy.seconds_until_next(0), 60)
        policy.on_failure(60)
        self.assertEqual(policy.seconds_until_next(60), 120)
        policy.on_failure(180)
        self.assertEqual(policy.seconds_until_next(180), 240)
        policy.on_failure(420)
        self.assertEqual(policy.seconds_until_next(420), 300)
        policy.on_failure(720)
        self.assertEqual(policy.seconds_until_next(720), 300)  # 封顶

    def test_success_resets(self):
        policy = RetryPolicy()
        policy.on_failure(0)
        policy.on_failure(60)
        policy.on_success(180)
        self.assertEqual(policy.failures, 0)
        self.assertEqual(policy.seconds_until_next(180), 300)

    def test_should_try(self):
        policy = RetryPolicy()
        self.assertTrue(policy.should_try(0))
        policy.on_failure(0)
        self.assertFalse(policy.should_try(30))
        self.assertTrue(policy.should_try(60))


if __name__ == "__main__":
    unittest.main()
