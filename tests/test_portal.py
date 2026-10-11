"""画像加载与状态机单元测试。"""
import json
import unittest
from pathlib import Path

from campus_auth.portal import DEFAULT_PROFILE, deep_merge, load_profile, ProfileError
from campus_auth.state import RetryPolicy

# 沙箱仅允许写工作区，临时文件直接放在测试目录下（工作区内）
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
_TMP_ROOT.mkdir(exist_ok=True)


class DeepMergeTests(unittest.TestCase):
    def test_nested_override(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 9}}
        self.assertEqual(deep_merge(base, override), {"a": {"x": 1, "y": 9}, "b": 3})

    def test_new_key_added(self):
        self.assertEqual(deep_merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})


class ProfileTests(unittest.TestCase):
    def test_default_profile_loads(self):
        profile = load_profile(None)
        self.assertEqual(profile.host, "10.0.0.1")
        self.assertEqual(profile.session_field, "sessionId")

    def test_custom_profile_overrides(self):
        file = _TMP_ROOT / "custom_portal.json"
        file.write_text(json.dumps({
            "portal": {"host": "10.0.0.1"},
            "workflow": {"credential_fields": {"username": "account"}},
        }), encoding="utf-8")
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
        profile = load_profile(None)
        self.assertEqual(profile.classify_error("账号或密码错误"), "password_wrong")
        self.assertEqual(profile.classify_error("请重新连网认证"), "session_expired")
        self.assertIsNone(profile.classify_error("未知信息"))


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
