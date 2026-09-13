from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "mailmerge_app" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
SAFETY_JS = (STATIC / "safety.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")


class FrontendIntegrityTests(unittest.TestCase):
    def test_every_els_reference_is_registered_and_present_in_html(self):
        match = re.search(r"const ids\s*=\s*\[(.*?)\];", APP_JS, flags=re.S)
        self.assertIsNotNone(match, "Could not find the frontend element registry")
        declared = set(re.findall(r"['\"]([A-Za-z][A-Za-z0-9_-]*)['\"]", match.group(1)))
        referenced = set(re.findall(r"\bels\.([A-Za-z_$][A-Za-z0-9_$]*)", APP_JS + "\n" + SAFETY_JS))
        html_ids = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", INDEX_HTML))

        self.assertEqual(sorted(referenced - declared), [], "frontend JavaScript references elements that are never registered")
        self.assertEqual(sorted(declared - html_ids), [], "registered frontend elements are missing from index.html")

    def test_safety_extension_loads_after_main_application(self):
        app_position = INDEX_HTML.find('/static/app.js')
        safety_position = INDEX_HTML.find('/static/safety.js')
        self.assertGreaterEqual(app_position, 0)
        self.assertGreater(safety_position, app_position)

    def test_queue_gate_tracks_stale_render_state(self):
        self.assertIn("!state.renderDirty", APP_JS)
        self.assertIn("invalidateReview", APP_JS)
        self.assertIn("renderRequestId", APP_JS)

    def test_html_email_preview_blocks_remote_network_content(self):
        self.assertIn("Content-Security-Policy", APP_JS)
        self.assertIn("default-src 'none'", APP_JS)
        self.assertIn("connect-src 'none'", APP_JS)

    def test_uncertain_queue_resolution_and_plain_text_html_guard_are_present(self):
        self.assertIn("resolve-sent", SAFETY_JS)
        self.assertIn("resolve-not-sent", SAFETY_JS)
        self.assertIn("message.body_html = ''", SAFETY_JS)

    def test_explicit_zero_row_selection_cannot_fall_back_to_all_rows(self):
        self.assertIn("NO_ROWS_SENTINEL", SAFETY_JS)
        self.assertIn("state.selectedRows.size === 0", SAFETY_JS)
        self.assertIn("payload.selected_rows = [NO_ROWS_SENTINEL]", SAFETY_JS)

    def test_queue_details_use_compact_bounded_api(self):
        self.assertIn("/detail?limit=${QUEUE_DETAIL_ROW_LIMIT}&needs_review_limit=${QUEUE_DETAIL_ROW_LIMIT}", SAFETY_JS)
        self.assertNotIn("const allItems = Array.isArray(campaign.items)", SAFETY_JS)

    def test_final_review_rejects_subject_line_breaks(self):
        self.assertIn("SUBJECT_LINE_ERROR", SAFETY_JS)
        self.assertIn("/\\r|\\n/.test(els.reviewSubject.value)", SAFETY_JS)


if __name__ == "__main__":
    unittest.main()
