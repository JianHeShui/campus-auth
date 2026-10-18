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
        with patch.object(network, "BoundHTTPConnection", return_value=conn) as ctor:
            self.assertTrue(network._ncsi_probe(network._NCSI_HOST, 3))
        ctor.assert_called_once_with(network._NCSI_HOST, 80, adapter=None, timeout=3)
        conn.request.assert_called_once_with("GET", "/connecttest.txt", headers={})

    def test_sends_host_header_for_ip_fallback(self):
        conn = _fake_connection(200, network._NCSI_EXPECT)
        with patch.object(network, "BoundHTTPConnection", return_value=conn):
            self.assertTrue(network._ncsi_probe("13.107.4.50", 3, use_host_header=True))
        conn.request.assert_called_once_with(
            "GET", "/connecttest.txt", headers={"Host": network._NCSI_HOST})

    def test_false_when_body_is_captive_portal(self):
        """网关劫持页虽然返回 200，但不含 NCSI 正文，必须判失败。"""
        conn = _fake_connection(200, "<script>location.href='http://10.0.0.1/eportal'</script>")
        with patch.object(network, "BoundHTTPConnection", return_value=conn):
            self.assertFalse(network._ncsi_probe(network._NCSI_HOST, 3))

    def test_false_on_non_200_status(self):
        conn = _fake_connection(502, network._NCSI_EXPECT)
        with patch.object(network, "BoundHTTPConnection", return_value=conn):
            self.assertFalse(network._ncsi_probe(network._NCSI_HOST, 3))

    def test_false_on_connection_error(self):
        with patch.object(network, "BoundHTTPConnection", side_effect=OSError("boom")):
            self.assertFalse(network._ncsi_probe(network._NCSI_HOST, 3))

    def test_closes_connection(self):
        conn = _fake_connection(200, network._NCSI_EXPECT)
        with patch.object(network, "BoundHTTPConnection", return_value=conn):
            network._ncsi_probe(network._NCSI_HOST, 3)
        conn.close.assert_called_once()

    def test_passes_adapter_to_bind_interface(self):
        """多网卡时必须把 adapter 传给 BoundHTTPConnection，避免探测走错网卡。"""
        conn = _fake_connection(200, network._NCSI_EXPECT)
        adapter = MagicMock()
        with patch.object(network, "BoundHTTPConnection", return_value=conn) as ctor:
            self.assertTrue(network._ncsi_probe(network._NCSI_HOST, 3, adapter=adapter))
        ctor.assert_called_once_with(network._NCSI_HOST, 80, adapter=adapter, timeout=3)


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
        probe.assert_called_once_with(network._NCSI_HOST, 5.0, adapter=None)

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

    def test_passes_adapter_through_to_ncsi_probe(self):
        """多网卡时必须把 adapter 透传给 NCSI 探测（否则可能走错网卡误判未联网）。"""
        adapter = MagicMock()
        with patch.object(network, "_ncsi_probe", return_value=True) as probe:
            self.assertTrue(network.internet_ok_by_ip(adapter=adapter))
        probe.assert_called_once_with(network._NCSI_IPS[0], 3.0,
                                      use_host_header=True, adapter=adapter)


class ExtractPortalUrlTests(unittest.TestCase):
    def test_location_header(self):
        self.assertEqual(network._extract_portal_url(
            "http://10.0.0.1/eportal/index.jsp?wlanuserip=1.2.3.4", ""), "10.0.0.1")

    def test_js_location_href(self):
        body = '<script>location.href="http://10.0.0.1/eportal/index.jsp?x=1"</script>'
        self.assertEqual(network._extract_portal_url("", body), "10.0.0.1")

    def test_meta_refresh(self):
        body = '<meta http-equiv="refresh" content="0;url=http://portal.example.edu.cn/portal/">'
        self.assertEqual(network._extract_portal_url("", body), "portal.example.edu.cn")

    def test_form_action(self):
        body = '<form action="https://sso.example.edu.cn/cas/login">'
        self.assertEqual(network._extract_portal_url("", body), "sso.example.edu.cn")

    def test_eportal_url_fallback(self):
        body = "go to http://10.0.0.1/eportal/index.jsp now"
        self.assertEqual(network._extract_portal_url("", body), "10.0.0.1")

    def test_non_standard_port_kept(self):
        self.assertEqual(network._extract_portal_url("http://10.0.0.1:8080/portal/", ""),
                         "10.0.0.1:8080")

    def test_no_portal_returns_empty(self):
        self.assertEqual(network._extract_portal_url("", "<html>hello</html>"), "")


class DetectPortalHostTests(unittest.TestCase):
    @staticmethod
    def _conn_factory(responses):
        """responses: host -> (status, location, body) 或 Exception 实例。"""
        def factory(host, port, adapter=None, timeout=0):
            item = responses.get(host)
            if item is None:
                raise OSError("unreachable")
            if isinstance(item, Exception):
                raise item
            status, location, body = item
            conn = MagicMock()
            resp = MagicMock()
            resp.status = status
            resp.getheader.return_value = location
            resp.read.return_value = body.encode("utf-8")
            conn.getresponse.return_value = resp
            return conn
        return factory

    def test_uses_location_redirect(self):
        factory = self._conn_factory({
            "www.baidu.com": (302, "http://10.0.0.1/eportal/index.jsp?x=1", ""),
        })
        with patch.object(network, "BoundHTTPConnection", side_effect=factory):
            host, evidence = network.detect_portal_host()
        self.assertEqual(host, "10.0.0.1")
        self.assertTrue(any("302" in line for line in evidence))

    def test_js_redirect_in_body(self):
        factory = self._conn_factory({
            "www.baidu.com": (200, "",
                              '<script>location.href="http://10.0.0.1/eportal/index.jsp"</script>'),
        })
        with patch.object(network, "BoundHTTPConnection", side_effect=factory):
            host, _ = network.detect_portal_host()
        self.assertEqual(host, "10.0.0.1")

    def test_dns_failure_falls_back_to_public_ip(self):
        factory = self._conn_factory({
            "www.baidu.com": OSError("getaddrinfo failed"),
            "223.5.5.5": (302, "http://10.0.0.1/eportal/index.jsp", ""),
        })
        with patch.object(network, "BoundHTTPConnection", side_effect=factory):
            host, evidence = network.detect_portal_host()
        self.assertEqual(host, "10.0.0.1")
        self.assertTrue(any("失败" in line for line in evidence))

    def test_all_targets_fail_returns_none_with_evidence(self):
        factory = self._conn_factory({})
        with patch.object(network, "BoundHTTPConnection", side_effect=factory):
            host, evidence = network.detect_portal_host()
        self.assertIsNone(host)
        self.assertGreaterEqual(len(evidence), 5)

    def test_online_without_captive_returns_none(self):
        factory = self._conn_factory({
            "www.baidu.com": (200, "", "<html>baidu</html>"),
            "223.5.5.5": (200, "", "ok"),
            "119.29.29.29": (200, "", "ok"),
            "180.76.76.76": (200, "", "ok"),
            "114.114.114.114": (200, "", "ok"),
        })
        with patch.object(network, "BoundHTTPConnection", side_effect=factory):
            host, evidence = network.detect_portal_host()
        self.assertIsNone(host)
        self.assertTrue(any("未发现认证页跳转" in line for line in evidence))


if __name__ == "__main__":
    unittest.main()
