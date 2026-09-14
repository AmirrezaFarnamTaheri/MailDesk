from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "mailmerge_app" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")


class FrontendIntegrityTests(unittest.TestCase):
    # Aliases keep focused frontend assertions concise while sharing the same
    # immutable source snapshots used by the rest of this integrity suite.
    html = INDEX_HTML
    js = APP_JS

    def test_every_els_reference_is_registered_and_present_in_html(self):
        match = re.search(r"const ids\s*=\s*\[(.*?)\];", APP_JS, flags=re.S)
        self.assertIsNotNone(match, "Could not find the frontend element registry")
        declared = set(re.findall(r"['\"]([A-Za-z][A-Za-z0-9_-]*)['\"]", match.group(1)))
        referenced = set(re.findall(r"\bels\.([A-Za-z_$][A-Za-z0-9_$]*)", APP_JS))
        html_ids = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", INDEX_HTML))

        self.assertEqual(sorted(referenced - declared), [], "frontend JavaScript references elements that are never registered")
        self.assertEqual(sorted(declared - html_ids), [], "registered frontend elements are missing from index.html")

    def test_single_frontend_script_has_no_patch_layer(self):
        self.assertIn('/static/app.js', INDEX_HTML)
        self.assertNotIn('/static/safety.js', INDEX_HTML)
        self.assertFalse((STATIC / "safety.js").exists())

    def test_queue_gate_tracks_stale_render_state(self):
        self.assertIn("!state.renderDirty", APP_JS)
        self.assertIn("invalidateReview", APP_JS)
        self.assertIn("renderRequestId", APP_JS)

    def test_html_email_preview_blocks_remote_network_content(self):
        self.assertIn("Content-Security-Policy", APP_JS)
        self.assertIn("default-src 'none'", APP_JS)
        self.assertIn("connect-src 'none'", APP_JS)

    def test_uncertain_queue_resolution_and_plain_text_html_guard_are_integrated(self):
        self.assertIn("resolve-sent", APP_JS)
        self.assertIn("resolve-not-sent", APP_JS)
        self.assertIn("m.body_html=''", APP_JS)
        self.assertIn("HTML_EDIT_WARNING", APP_JS)

    def test_row_selection_has_normal_empty_and_all_semantics(self):
        self.assertIn("state.selectedRows.size===state.allRowNumbers.length?null:[...state.selectedRows]", APP_JS)
        self.assertNotIn("NO_ROWS_SENTINEL", APP_JS)

    def test_queue_details_use_compact_bounded_api(self):
        self.assertIn("/detail?limit=${QUEUE_DETAIL_ROW_LIMIT}&needs_review_limit=${QUEUE_DETAIL_ROW_LIMIT}", APP_JS)
        self.assertNotIn("const allItems = Array.isArray(campaign.items)", APP_JS)

    def test_final_review_rejects_subject_line_breaks(self):
        self.assertIn("SUBJECT_LINE_ERROR", APP_JS)
        self.assertIn(r"/\r|\n/.test(m.subject)", APP_JS)

    def test_optional_controls_are_progressively_disclosed(self):
        self.assertIn('More recipient options', INDEX_HTML)
        self.assertNotIn('<details class="advanced" open>', INDEX_HTML)
        self.assertIn('Optional: pacing and duplicate handling', INDEX_HTML)

    def test_duplicate_readiness_and_approval_ui_is_removed(self):
        for token in ('campaignReadiness', 'reviewedCheck', 'refreshBeforeReview', 'batchChip', 'healthChip', 'refreshButton'):
            self.assertNotIn(token, INDEX_HTML)
            self.assertNotIn(token, APP_JS)

    def test_sheet_viewer_and_expanded_tour_are_wired(self):
        self.assertIn('openSheetViewerButton', self.html)
        self.assertIn('sheetViewerDialog', self.html)
        self.assertIn('/api/imports/${state.importId}/rows', self.js)
        self.assertIn("title:'Set up senders carefully'", self.js)
        self.assertIn("title:'Inspect the source'", self.js)
        self.assertGreaterEqual(self.js.count("title:'"), 8)

    def test_first_run_tour_is_wired_and_replayable(self):
        self.assertIn('id="tourOverlay"', INDEX_HTML)
        self.assertIn('id="startTourButton"', INDEX_HTML)
        self.assertIn('const tourSteps=', APP_JS)
        self.assertIn('TOUR_STORAGE_KEY', APP_JS)
        self.assertIn("localStorage.getItem('maildesk-onboarded')", APP_JS)
        self.assertIn('requestAnimationFrame(startTour)', APP_JS)

    def test_wizard_does_not_restore_a_stale_step_without_runtime_state(self):
        self.assertNotIn('step:state.step', APP_JS)
        self.assertIn('if(data.sourceTab)setSourceTab(data.sourceTab);setStep(1);', APP_JS)

    def test_send_confirmation_is_simple_and_mode_specific(self):
        self.assertIn("`SEND ${r.messages.length}`", APP_JS)
        self.assertNotIn("batch_id[:8]", APP_JS)
        self.assertNotIn("reviewed:", APP_JS)

    def test_final_action_label_matches_delivery_mode(self):
        self.assertIn('Run dry test', APP_JS)
        self.assertIn('Open ${count} browser draft', APP_JS)
        self.assertIn('Create ${count} Gmail draft', APP_JS)
        self.assertIn('`Send ${count} ${plural}`', APP_JS)

    def test_placeholder_mapping_ui_is_wired_to_render_payload(self):
        self.assertIn('id="placeholderMappingList"', INDEX_HTML)
        self.assertIn('id="autoMapPlaceholdersButton"', INDEX_HTML)
        self.assertIn('templatePlaceholderInfo', APP_JS)
        self.assertIn('placeholder_mappings:Object.fromEntries', APP_JS)

    def test_live_sheet_stays_beside_message_preview(self):
        self.assertIn('id="liveSheetCard"', INDEX_HTML)
        self.assertIn('id="liveSheetTable"', INDEX_HTML)
        self.assertIn('function renderLiveSheet()', APP_JS)
        self.assertIn("findIndex(message=>String(message.row_number)===String(row._row))", APP_JS)

    def test_browser_sender_setup_prefers_detected_accounts(self):
        self.assertIn('id="detectedBrowserAccounts"', INDEX_HTML)
        self.assertIn('id="rescanBrowserProfilesButton"', INDEX_HTML)
        self.assertIn('/api/browser-profiles?refresh=true', APP_JS)
        self.assertIn('p?.gmail_accounts||[]', APP_JS)
        self.assertIn('Can’t see the account?', INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
