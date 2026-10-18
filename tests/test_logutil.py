"""日志模块测试：脱敏、轮转、写入失败静默。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_auth import logutil


class MaskTests(unittest.TestCase):
    def test_short_value_fully_masked(self):
        self.assertEqual(logutil.mask("ab"), "***")
        self.assertEqual(logutil.mask(""), "")

    def test_long_value_keeps_edges(self):
        masked = logutil.mask("1234567890")
        self.assertEqual(masked, "12***90")
        self.assertNotIn("3456", masked)

    def test_none_and_non_string(self):
        self.assertEqual(logutil.mask(None), "")
        self.assertEqual(logutil.mask(1234567), "12***67")


class ScrubTests(unittest.TestCase):
    def test_json_fields_masked(self):
        raw = '{"username":"alice","password":"secret123","sessionId":"abc123def","ticket":"ST-123456"}'
        cleaned = logutil.scrub(raw)
        for secret in ("alice", "secret123", "abc123def", "ST-123456"):
            self.assertNotIn(secret, cleaned)
        self.assertIn('"username":"***"', cleaned)

    def test_croypto_and_cookie_masked(self):
        raw = "croypto=Qvy2L55c2aTCHUc6uX/Llw== cookie=SESSION=abcdef"
        cleaned = logutil.scrub(raw)
        self.assertNotIn("Qvy2L55c2aTCHUc6uX", cleaned)
        self.assertNotIn("abcdef", cleaned)

    def test_plain_text_untouched(self):
        raw = "captive探测 http://www.baidu.com/ -> HTTP 200"
        self.assertEqual(logutil.scrub(raw), raw)

    def test_empty(self):
        self.assertEqual(logutil.scrub(""), "")


class WriteLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "auth-debug.log"
        self._patch = patch.object(logutil, "LOG_PATH", self.path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_writes_timestamped_line(self):
        logutil.write_log("hello")
        content = self.path.read_text(encoding="utf-8")
        self.assertRegex(content, r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] hello")
        self.assertEqual(content.count("\n"), 1)

    def test_rotates_when_over_limit(self):
        self.path.write_text("old-data-exceeding-limit", encoding="utf-8")
        with patch.object(logutil, "MAX_BYTES", 10):
            logutil.write_log("new")
        backup = self.path.with_name(self.path.name + ".1")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "old-data-exceeding-limit")
        self.assertIn("new", self.path.read_text(encoding="utf-8"))

    def test_write_failure_is_silent(self):
        # 指向一个非法路径（目录不存在且父路径是文件）不应抛异常
        with patch.object(logutil, "LOG_PATH", Path(self.tmp.name) / "file.txt" / "x.log"):
            (Path(self.tmp.name) / "file.txt").write_text("x", encoding="utf-8")
            logutil.write_log("should not raise")

    def test_write_scrubbed_log_masks_before_write(self):
        logutil.write_scrubbed_log('{"password":"secret123"}')
        content = self.path.read_text(encoding="utf-8")
        self.assertNotIn("secret123", content)
        self.assertIn("***", content)


if __name__ == "__main__":
    unittest.main()
