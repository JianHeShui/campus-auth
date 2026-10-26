"""命令行参数解析测试：自动保护间隔的优先级与范围钳制（不启动守护循环）。"""
import argparse
import unittest

from campus_auth import cli


def _args(**kwargs) -> argparse.Namespace:
    base = dict(recheck_interval=None, max_interval=None, no_network_events=False)
    base.update(kwargs)
    return argparse.Namespace(**base)


class _Profile:
    def __init__(self, watch=None):
        self.watch = watch


class ResolveWatchSettingsTests(unittest.TestCase):
    def test_defaults_without_watch_section(self):
        self.assertEqual(cli._resolve_watch_settings(_args(), _Profile(None)), (60, 300, True))
        self.assertEqual(cli._resolve_watch_settings(_args(), object()), (60, 300, True))

    def test_profile_values_are_used(self):
        profile = _Profile({"recheck_interval": 30, "max_interval": 120, "network_events": False})
        self.assertEqual(cli._resolve_watch_settings(_args(), profile), (30, 120, False))

    def test_cli_overrides_profile(self):
        profile = _Profile({"recheck_interval": 30, "max_interval": 120})
        args = _args(recheck_interval=10, max_interval=90)
        self.assertEqual(cli._resolve_watch_settings(args, profile), (10, 90, True))

    def test_no_network_events_flag_wins(self):
        profile = _Profile({"network_events": True})
        self.assertFalse(cli._resolve_watch_settings(_args(no_network_events=True), profile)[2])

    def test_values_are_clamped_to_range(self):
        profile = _Profile({"recheck_interval": 1, "max_interval": 99999})
        self.assertEqual(cli._resolve_watch_settings(_args(), profile)[:2], (5, 3600))
        args = _args(recheck_interval=0, max_interval=-5)
        self.assertEqual(cli._resolve_watch_settings(args, _Profile(None))[:2], (5, 5))

    def test_invalid_profile_value_falls_back(self):
        profile = _Profile({"recheck_interval": "abc", "max_interval": None})
        self.assertEqual(cli._resolve_watch_settings(_args(), profile)[:2], (60, 300))

    def test_recheck_interval_default_is_60(self):
        """v0.3.2：默认在线复核从 300 秒缩短到 60 秒。"""
        self.assertEqual(cli.DEFAULT_RECHECK_INTERVAL, 60)
        self.assertEqual(cli.DEFAULT_MAX_INTERVAL, 300)


if __name__ == "__main__":
    unittest.main()
