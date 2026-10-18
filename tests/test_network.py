"""网络层 NCSI 探测测试：mock HTTP 与 subprocess，不触网、不执行真实 ipconfig。"""
import unittest
from unittest.mock import MagicMock, patch

from campus_auth import network


def _fake_connection(status: int = 200, body: str = ""):
    """构造一个假的 HTTPConnection：getresponse() 返回指定状态与正文。"""
    conn = MagicMock()
    response = MagicMock()
    response.status = status
    response.read.return_value = body.encode("utf-8")
    conn.getresponse.return_value = response
    return conn


class NcsiProbeTests(unittest.TestCase):
    def test_true_when_body_matches_expected(self):
        conn = _fake_connection(200, "Microsoft Connect Test\r\n")
        with patch.object(network.http.client, "HTTPConnection", return_value=conn) as ctor:
            self.assertTrue(network._ncsi_probe(network._NCSI_HOST, 3))
        ctor.assert_called_once_with(network._NCSI_HOST, 80, timeout=3)
        conn.request.assert_called_once_with("GET", "/connecttest.txt", headers={})

    def test_sends_host_header_for_ip_fallback(self):
        conn = _fake_connection(200, network._NCSI_EXPECT)
        with patch.object(network.http.client, "HTTPConnection", return_value=conn):
            self.assertTrue(network._ncsi_probe("13.107.4.50", 3, use_host_header=True))
        conn.request.assert_called_once_with(
            "GET", "/connecttest.txt", headers={"Host": network._NCSI_HOST})

    def test_false_when_body_is_captive_portal(self):
        """网关劫持页虽然返回 200，但不含 NCSI 正文，必须判失败。"""
        conn = _fake_connection(200, "<script>location.href='http://10.0.0.1/eportal'</script>")
        with patch.object(network.http.client, "HTTPConnection", return_value=conn):
            self.assertFalse(network._ncsi_probe(network._NCSI_HOST, 3))

    def test_false_on_non_200_status(self):
        conn = _fake_connection(502, network._NCSI_EXPECT)
        with patch.object(network.http.client, "HTTPConnection", return_value=conn):
            self.assertFalse(network._ncsi_probe(network._NCSI_HOST, 3))

    def test_false_on_connection_error(self):
        with patch.object(network.http.client, "HTTPConnection", side_effect=OSError("boom")):
            self.assertFalse(network._ncsi_probe(network._NCSI_HOST, 3))

    def test_closes_connection(self):
        conn = _fake_connection(200, network._NCSI_EXPECT)
        with patch.object(network.http.client, "HTTPConnection", return_value=conn):
            network._ncsi_probe(network._NCSI_HOST, 3)
        conn.close.assert_called_once()


class TriggerNcsiRefreshTests(unittest.TestCase):
    def test_flushes_dns_then_probes_domain(self):
        conn = _fake_connection(200, network._NCSI_EXPECT)
        with patch("subprocess.run") as run, \
             patch.object(network.http.client, "HTTPConnection", return_value=conn):
            network.trigger_windows_ncsi_refresh()
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0], ["ipconfig", "/flushdns"])

    def test_domain_success_skips_ip_fallback(self):
        with patch("subprocess.run"), \
             patch.object(network, "_ncsi_probe", return_value=True) as probe:
            network.trigger_windows_ncsi_refresh()
        probe.assert_called_once_with(network._NCSI_HOST, 5.0)

    def test_falls_back_to_public_ips_in_order(self):
        results = iter([False, False, True])  # 域名失败 → 第一个 IP 失败 → 第二个 IP 成功
        with patch("subprocess.run"), \
             patch.object(network, "_ncsi_probe", side_effect=lambda *a, **kw: next(results)) as probe:
            network.trigger_windows_ncsi_refresh(timeout=2.5)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(probe.call_args_list[0].args, (network._NCSI_HOST, 2.5))
        self.assertEqual(probe.call_args_list[1].args, (network._NCSI_IPS[0], 2.5))
        self.assertTrue(probe.call_args_list[1].kwargs.get("use_host_header"))
        self.assertEqual(probe.call_args_list[2].args, (network._NCSI_IPS[1], 2.5))
        self.assertTrue(probe.call_args_list[2].kwargs.get("use_host_header"))

    def test_all_probes_fail_silently(self):
        with patch("subprocess.run"), \
             patch.object(network, "_ncsi_probe", return_value=False):
            network.trigger_windows_ncsi_refresh()  # 不应抛异常

    def test_flushdns_failure_does_not_abort_probe(self):
        with patch("subprocess.run", side_effect=OSError("no ipconfig")), \
             patch.object(network, "_ncsi_probe", return_value=True) as probe:
            network.trigger_windows_ncsi_refresh()
        probe.assert_called_once()

    def test_unexpected_probe_error_is_swallowed(self):
        """本函数承诺失败静默：探测抛出未预期异常也不能影响认证主流程。"""
        with patch("subprocess.run"), \
             patch.object(network, "_ncsi_probe", side_effect=RuntimeError("boom")):
            network.trigger_windows_ncsi_refresh()  # 不应抛异常


class InternetOkByIpTests(unittest.TestCase):
    """联网判定优先用 NCSI 检测点内容校验，NCSI 不可用时回退旧逻辑。"""

    def test_uses_ncsi_probe_first(self):
        with patch.object(network, "_ncsi_probe", side_effect=[False, True]) as probe, \
             patch.object(network, "BoundHTTPConnection") as conn_cls:
            self.assertTrue(network.internet_ok_by_ip())
        self.assertEqual(probe.call_count, 2)
        conn_cls.assert_not_called()

    def test_ncsi_all_fail_falls_back_and_handles_errors(self):
        with patch.object(network, "_ncsi_probe", return_value=False), \
             patch.object(network, "BoundHTTPConnection", side_effect=OSError("no route")):
            self.assertFalse(network.internet_ok_by_ip())


if __name__ == "__main__":
    unittest.main()
