from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mailmerge_app.browser_profiles import MAX_BROWSER_COMPOSE_URL_CHARS, _safe_profile_dir, compose_url, launch_url


class BrowserProfileSecurityTests(unittest.TestCase):
    def test_profile_directory_must_be_direct_child(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Default").mkdir()
            self.assertEqual(_safe_profile_dir(root, "Default"), "Default")
            self.assertIsNone(_safe_profile_dir(root, "../Default"))
            self.assertIsNone(_safe_profile_dir(root, str((root / "Default").resolve())))
            self.assertIsNone(_safe_profile_dir(root, "missing"))

    def test_browser_launcher_rejects_non_gmail_urls(self):
        profile = {"executable": "browser.exe", "profile_dir": "Default"}
        with patch("mailmerge_app.browser_profiles.subprocess.Popen") as popen:
            with self.assertRaises(ValueError):
                launch_url(profile, "https://example.com/")
            popen.assert_not_called()

    def test_browser_launcher_binds_the_exact_user_data_and_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable = root / "browser.exe"; executable.write_bytes(b"")
            (root / "Default").mkdir()
            profile = {"executable": str(executable), "user_data": str(root), "profile_dir": "Default"}
            with patch("mailmerge_app.browser_profiles.subprocess.Popen") as popen:
                launch_url(profile, "https://mail.google.com/mail/u/0/#inbox")
            args = popen.call_args.args[0]
            self.assertIn(f"--user-data-dir={root}", args)
            self.assertIn("--profile-directory=Default", args)

    def test_browser_compose_url_is_bounded_below_os_command_line_limits(self):
        self.assertLess(MAX_BROWSER_COMPOSE_URL_CHARS, 32767)
        with self.assertRaisesRegex(ValueError, "too large"):
            compose_url("to@example.com", "Subject", "x" * (MAX_BROWSER_COMPOSE_URL_CHARS + 1))


if __name__ == "__main__":
    unittest.main()
