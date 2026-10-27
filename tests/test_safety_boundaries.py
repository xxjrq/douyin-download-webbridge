import json
import pathlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts"))
import douyin_download as MODULE


class BrowserSelectionTests(unittest.TestCase):
    def setUp(self):
        self.browsers = [
            {"displayName": "工作账号", "browserId": "browser-a"},
            {"displayName": "个人账号", "browserId": "browser-b"},
        ]

    def test_explicit_name_selects_only_that_browser(self):
        self.assertEqual(
            MODULE.select_browser(self.browsers, "个人账号"), self.browsers[1]
        )

    def test_explicit_id_selects_only_that_browser(self):
        self.assertEqual(
            MODULE.select_browser(self.browsers, "browser-a"), self.browsers[0]
        )

    def test_explicit_missing_browser_fails_without_fallback(self):
        self.assertIsNone(MODULE.select_browser(self.browsers, "offline-account"))

    def test_ambiguous_default_does_not_choose_first_account(self):
        self.assertIsNone(MODULE.select_browser(self.browsers))

    def test_single_online_browser_is_safe_default(self):
        self.assertEqual(MODULE.select_browser(self.browsers[:1]), self.browsers[0])

    def test_named_default_is_preferred(self):
        browsers = self.browsers + [
            {"displayName": "自媒体", "browserId": "browser-c"}
        ]
        self.assertEqual(MODULE.select_browser(browsers), browsers[2])


class AccessBarrierTests(unittest.TestCase):
    def test_login_and_verification_prompts_are_recognized(self):
        self.assertTrue(MODULE.is_access_barrier_text("请登录后继续"))
        self.assertTrue(MODULE.is_access_barrier_text("请完成安全验证"))

    def test_api_auth_error_is_recognized(self):
        payload = {"status_code": 1, "status_msg": "请登录后重试"}
        with self.assertRaises(MODULE.AccessBarrierError):
            MODULE.raise_if_access_barrier_payload(payload)

    def test_non_success_detail_status_stops_without_retry(self):
        with self.assertRaises(MODULE.AccessBarrierError):
            MODULE.raise_if_access_barrier_payload({"status_code": 8})

    def test_normal_post_description_is_not_treated_as_auth_error(self):
        payload = {"status_code": 0, "desc": "登录后我们再聊这段往事"}
        self.assertFalse(MODULE.is_access_barrier_payload(payload))

    def test_detected_page_barrier_stops_before_extraction(self):
        state = {"blocked": True, "href": "https://www.douyin.com/login"}
        with patch.object(
            MODULE,
            "wb",
            return_value={"ok": True, "result": json.dumps(state)},
        ):
            with self.assertRaises(MODULE.AccessBarrierError):
                MODULE.check_page_access_barrier("browser-a", "tab-1")

    def test_page_check_fails_closed_on_malformed_or_untrusted_results(self):
        bad_results = [
            "{not-json",
            None,
            [False],
            "not a state object",
            {},
            {"href": "https://www.douyin.com/video/123"},
            {"blocked": "false"},
        ]
        for result in bad_results:
            with self.subTest(result=result), patch.object(
                MODULE, "wb", return_value={"ok": True, "result": result}
            ):
                with self.assertRaises(MODULE.AccessBarrierError):
                    MODULE.check_page_access_barrier("browser-a", "tab-1")

    def test_evaluate_checks_page_state_after_execution(self):
        states = iter([
            {"ok": True, "result": json.dumps({"blocked": False})},
            {"ok": True, "result": "video title"},
            {"ok": True, "result": json.dumps({"blocked": True})},
        ])
        with patch.object(MODULE, "wb", side_effect=lambda *args, **kwargs: next(states)) as bridge:
            with self.assertRaises(MODULE.AccessBarrierError):
                MODULE.evaluate("browser-a", "tab-1", "document.title")
        self.assertEqual(bridge.call_count, 3)

    def test_media_endpoint_access_limit_raises_stop_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "blocked.mp4"
            with patch.object(MODULE, "run", return_value=(0, "403\t0\t\ttext/html", "")):
                with self.assertRaises(MODULE.AccessBarrierError):
                    MODULE.download("https://media.example/blocked", str(path))
            self.assertFalse(path.exists())

    def test_login_redirect_is_treated_as_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "blocked.mp4"
            with patch.object(
                MODULE, "run",
                return_value=(0, "302\t0\thttps://www.douyin.com/login\ttext/html", ""),
            ):
                with self.assertRaises(MODULE.AccessBarrierError):
                    MODULE.download("https://media.example/blocked", str(path))

    def test_success_status_with_html_body_is_not_saved_as_media(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "blocked.mp4"
            path.write_text("challenge", encoding="utf-8")
            with patch.object(
                MODULE, "run", return_value=(0, "200\t9\t\ttext/html", "")
            ):
                with self.assertRaises(MODULE.AccessBarrierError):
                    MODULE.download("https://media.example/blocked", str(path))
            self.assertFalse(path.exists())

    def test_missing_detail_state_fails_closed(self):
        with self.assertRaises(MODULE.AccessBarrierError):
            MODULE.raise_if_access_barrier_payload({
                "detailReady": False, "status_code": 0,
            })

    def test_missing_aweme_detail_error_marker_is_normalized(self):
        for marker in ("no aweme_detail", "no_aweme_detail"):
            with self.subTest(marker=marker), self.assertRaises(MODULE.AccessBarrierError):
                MODULE.raise_if_access_barrier_payload({"err": marker})

    def test_unreadable_detail_stops_media_type_retries(self):
        with patch.object(MODULE, "fetch_kind_probe", return_value=None) as fetch:
            with self.assertRaises(MODULE.AccessBarrierError):
                MODULE.detect_kind("browser-a", "tab-1", "123456789012")
        fetch.assert_called_once_with("browser-a", "tab-1", "123456789012", wait=0)

    def test_login_barrier_preserves_task_tab(self):
        with patch.object(sys, "argv", ["douyin_download.py", "123456789012"]), \
                patch.object(MODULE, "check_bridge", return_value=[{
                    "displayName": "自媒体", "browserId": "browser-a",
                }]), \
                patch.object(MODULE, "parse_input", return_value=("123456789012", "video")), \
                patch.object(MODULE, "navigate_to", return_value="tab-1"), \
                patch.object(MODULE, "detect_kind", side_effect=MODULE.AccessBarrierError()), \
                patch.object(MODULE, "wb") as bridge_command:
            self.assertEqual(MODULE.main(), 2)
        bridge_command.assert_not_called()


class ExplicitBrowserIntegrationTests(unittest.TestCase):
    def test_missing_explicit_browser_stops_before_input_or_navigation(self):
        with patch.object(sys, "argv", [
            "douyin_download.py", "123456789012", "--browser", "offline-account",
        ]), patch.object(MODULE, "check_bridge", return_value=[{
            "displayName": "other-account", "browserId": "browser-b",
        }]), patch.object(MODULE, "parse_input") as parse_input, \
                patch.object(MODULE, "navigate_to") as navigate:
            self.assertEqual(MODULE.main(), 1)
        parse_input.assert_not_called()
        navigate.assert_not_called()


class NoteImageSourceTests(unittest.TestCase):
    def test_dom_original_must_match_detail_image_id(self):
        detail = {
            "desc": "requested work",
            "imgs": [{
                "urls": ["https://img.example/targetimageid12345678901234567890~tplv-q75.jpeg"]
            }],
        }
        recommendations = [
            "https://img.example/recommendimage12345678901234567890~noop.jpeg"
        ]
        images, _ = MODULE.select_note_images(detail, recommendations)
        self.assertEqual(len(images), 1)
        self.assertIn("targetimageid12345678901234567890", images[0][0])
        self.assertNotIn("recommendimage", images[0][0])

    def test_missing_detail_image_list_fails_instead_of_using_dom(self):
        recommendations = [
            "https://img.example/recommendimage12345678901234567890~noop.jpeg"
        ]
        images, _ = MODULE.select_note_images(None, recommendations)
        self.assertEqual(images, [])

    def test_note_fallback_does_not_download_page_wide_dom_images(self):
        recommendation = "https://img.example/recommendimage12345678901234567890~noop.jpeg"
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(MODULE, "fetch_note_detail", return_value=None), \
                patch.object(MODULE, "fetch_note_images", return_value=[recommendation]) as fetch_dom, \
                patch.object(MODULE, "download") as download:
            result = MODULE.try_note(
                "browser-a", "tab-1", "123456789012", SimpleNamespace(out=directory)
            )
        self.assertEqual(result, [])
        fetch_dom.assert_not_called()
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
