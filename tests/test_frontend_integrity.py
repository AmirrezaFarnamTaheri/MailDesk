from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "mailmerge_app" / "static" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "mailmerge_app" / "static" / "index.html").read_text(encoding="utf-8")


class FrontendIntegrityTests(unittest.TestCase):
    def test_every_els_reference_is_registered_and_present_in_html(self):
        match = re.search(r"const ids\s*=\s*\[(.*?)\];", APP_JS, flags=re.S)
        self.assertIsNotNone(match, "Could not find the frontend element registry")
        declared = set(re.findall(r"['\"]([A-Za-z][A-Za-z0-9_-]*)['\"]", match.group(1)))
        referenced = set(re.findall(r"\bels\.([A-Za-z_$][A-Za-z0-9_$]*)", APP_JS))
        html_ids = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", INDEX_HTML))

        self.assertEqual(sorted(referenced - declared), [], "app.js references elements that are never registered")
        self.assertEqual(sorted(declared - html_ids), [], "registered frontend elements are missing from index.html")

    def test_queue_gate_tracks_stale_render_state(self):
        self.assertIn("!state.renderDirty", APP_JS)
        self.assertIn("invalidateReview", APP_JS)
        self.assertIn("renderRequestId", APP_JS)

    def test_html_email_preview_blocks_remote_network_content(self):
        self.assertIn("Content-Security-Policy", APP_JS)
        self.assertIn("default-src 'none'", APP_JS)
        self.assertIn("connect-src 'none'", APP_JS)


if __name__ == "__main__":
    unittest.main()
