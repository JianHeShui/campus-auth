"""门户类型探测测试：mock 特征响应，验证分类逻辑（不触网）。"""
import unittest
from unittest.mock import patch

from campus_auth.detect import (
    _PROBE_PATHS,
    _looks_like_javascript,
    _probe_all,
    parse_address,
    probe_portal,
)


def _fake_get(responses: dict[str, tuple]):
    """构造一个按路径返回响应的 _get 替身（精确匹配）。"""
    def fake(host, port, scheme, path, timeout=6):
        if path in responses:
            return responses[path]
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


class CasContentCheckTests(unittest.TestCase):
    """CAS 判定必须校验正文内容，不能只看 HTTP 200（防 SPA 万能 200 误判）。"""

    def test_spa_universal_200_html_is_not_cas(self):
        html = "<!DOCTYPE html><html><head><title>portal</title></head><body></body></html>"
        get = _fake_get({
            "/": (200, {}, html),
            "/sso-public/cas-login-new/main.js": (200, {}, html),
        })
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertNotEqual(result["type"], "华三 CAS SSO")

    def test_real_cas_javascript_detected(self):
        js = "!function(){window.__PLATFORM_SSO__=1;var a=1;}();"
        get = _fake_get({
            "/sso-public/cas-login-new/main.js":
                (200, {"content-type": "application/javascript"}, js),
        })
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "华三 CAS SSO")

    def test_javascript_detection_rules(self):
        self.assertTrue(_looks_like_javascript(200, {"content-type": "application/javascript"}, "var x=1;"))
        self.assertTrue(_looks_like_javascript(200, {}, "function boot(){}"))
        self.assertFalse(_looks_like_javascript(200, {}, "<!DOCTYPE html><html></html>"))
        self.assertFalse(_looks_like_javascript(404, {}, "function boot(){}"))
        self.assertFalse(_looks_like_javascript(200, {}, ""))

    def test_probe_all_covers_every_path(self):
        with patch("campus_auth.detect._get", _fake_get({})):
            results = _probe_all("10.0.0.1", 80, "http", 3)
        self.assertEqual(set(results), set(_PROBE_PATHS))

    def test_result_reports_elapsed(self):
        with patch("campus_auth.detect._get", _fake_get({})):
            result = probe_portal("10.0.0.1")
        self.assertIn("elapsed", result)
        self.assertGreaterEqual(result["elapsed"], 0)


class VendorFingerprintTests(unittest.TestCase):
    """阶段 0 新增厂商指纹：安朗/锐捷 ePortal/H3C iMC（来源 adapters.js + detect.ps1）。"""

    def test_anlang_detected_by_brand(self):
        get = _fake_get({"/": (200, {}, "欢迎使用安朗网络认证系统")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertTrue(result["recognized"])
        self.assertEqual(result["type"], "安朗/安腾")
        self.assertEqual(result["vendor"], "anlang")
        self.assertEqual(result["suggested_auth_mode"], "anlang")

    def test_anlang_detected_by_3848(self):
        get = _fake_get({"/": (200, {}, "<script>var clientPort = 3848;</script>")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["vendor"], "anlang")

    def test_anlang_detected_by_other_markers(self):
        for marker in ("amnoon", "an-link", "蓝蝶"):
            with self.subTest(marker=marker):
                get = _fake_get({"/": (200, {}, f"<title>{marker}</title>")})
                with patch("campus_auth.detect._get", get):
                    result = probe_portal("10.0.0.1")
                self.assertEqual(result["vendor"], "anlang")

    def test_ruijie_eportal_detected_by_interface_do(self):
        get = _fake_get({
            "/eportal/InterFace.do": (200, {}, "var url='/eportal/InterFace.do?method=pageInfo';"),
        })
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "锐捷 ePortal")
        self.assertEqual(result["vendor"], "ruijie_eportal")
        self.assertEqual(result["suggested_auth_mode"], "ruijie_eportal")
        # GUI 只认三大模板：template/mode 必须仍是已知值，语义不变
        self.assertEqual(result["template"], "通用（简单登录）")
        self.assertEqual(result["mode"], "simple")

    def test_ruijie_eportal_detected_by_password_encrypt(self):
        get = _fake_get({"/": (200, {}, "function passwordEncrypt(data) { return data; }")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["vendor"], "ruijie_eportal")

    def test_h3c_imc_detected_by_login_jsp(self):
        get = _fake_get({"/portal/login.jsp": (200, {}, "location.href = '?basip=10.0.0.1';")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "H3C iMC")
        self.assertEqual(result["vendor"], "h3c_imc")
        self.assertEqual(result["suggested_auth_mode"], "h3c_imc")
        self.assertEqual(result["mode"], "simple")

    def test_ruijie_eportal_wins_over_srun_params(self):
        """锐捷 ePortal 的 URL 也常带 wlanuserip：必须优先识别更具体的 ePortal 指纹。"""
        get = _fake_get({
            "/": (200, {}, "InterFace.do?wlanuserip=1.2.3.4&wlanacname=ac"),
        })
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["vendor"], "ruijie_eportal")
        self.assertNotEqual(result["type"], "深澜 Srun")

    def test_sam_plus_still_wins_over_eportal_fingerprint(self):
        """config.js 锐捷品牌/SSO 标记仍优先判锐捷 SAM+（保留现有优先级）。"""
        get = _fake_get({
            "/portal/assets/config.js": (200, {}, "锐捷网络 smpdomain"),
            "/": (200, {}, "InterFace.do passwordEncrypt"),
        })
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["type"], "锐捷 SAM+")
        self.assertEqual(result["vendor"], "ruijie_sam")
        self.assertEqual(result["suggested_auth_mode"], "workflow")

    def test_unknown_vendor_fields(self):
        with patch("campus_auth.detect._get", _fake_get({})):
            result = probe_portal("10.0.0.1")
        self.assertFalse(result["recognized"])
        self.assertEqual(result["vendor"], "unknown")
        self.assertEqual(result["suggested_auth_mode"], "simple")

    def test_unparsable_address_has_new_fields(self):
        result = probe_portal("")
        self.assertEqual(result["vendor"], "unknown")
        self.assertEqual(result["suggested_auth_mode"], "simple")
        self.assertEqual(result["mode"], "simple")
        self.assertIsNone(result["template"])

    def test_existing_vendors_report_vendor_and_suggested_mode(self):
        cases = [
            ({"/sso-public/cas-login-new/main.js": (200, {"content-type": "application/javascript"},
                                                    "var x=1;")}, "cas", "cas"),
            ({"/eportal/index.jsp": (200, {}, "wlanuserip=1.2.3.4")}, "srun", "srun"),
            ({"/": (200, {}, "Welcome to Dr.COM")}, "drcom", "drcom"),
            ({"/": (200, {}, "Huawei Agile Controller")}, "huawei", "simple"),
        ]
        for responses, vendor, suggested in cases:
            with self.subTest(vendor=vendor):
                with patch("campus_auth.detect._get", _fake_get(responses)):
                    result = probe_portal("10.0.0.1")
                self.assertEqual(result["vendor"], vendor)
                self.assertEqual(result["suggested_auth_mode"], suggested)

    def test_eportal_fallback_reports_unknown_vendor(self):
        get = _fake_get({"/eportal/adaptor/getOnlineUserInfo": (500, {}, "sessionId is required")})
        with patch("campus_auth.detect._get", get):
            result = probe_portal("10.0.0.1")
        self.assertEqual(result["vendor"], "unknown")
        self.assertEqual(result["suggested_auth_mode"], "workflow")

    def test_all_branches_keep_legacy_and_new_fields(self):
        """所有返回分支字段一致：旧字段（GUI 依赖）语义不变，新字段始终存在。"""
        required = {"recognized", "type", "template", "mode", "vendor",
                    "suggested_auth_mode", "evidence", "message", "elapsed"}
        scenarios = [
            {},
            {"/sso-public/cas-login-new/main.js":
                (200, {"content-type": "application/javascript"}, "var x=1;")},
            {"/portal/assets/config.js": (200, {}, "锐捷网络 smpdomain")},
            {"/eportal/index.jsp": (200, {}, "wlanuserip=1.2.3.4")},
            {"/": (200, {}, "安朗 anlang")},
        ]
        for responses in scenarios:
            with self.subTest(responses=list(responses)):
                with patch("campus_auth.detect._get", _fake_get(responses)):
                    result = probe_portal("10.0.0.1")
                self.assertEqual(required, set(result))
        # 地址无法解析分支同样适用
        self.assertEqual(required, set(probe_portal("")))


if __name__ == "__main__":
    unittest.main()
