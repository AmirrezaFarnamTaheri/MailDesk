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

    def test_html_ids_are_unique(self):
        html_ids = re.findall(r"\bid=[\"']([^\"']+)[\"']", INDEX_HTML)
        duplicates = sorted({html_id for html_id in html_ids if html_ids.count(html_id) > 1})
        self.assertEqual(duplicates, [], "duplicate HTML ids make labels and JavaScript references ambiguous")

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
        self.assertIn('Advanced delivery settings', INDEX_HTML)
        self.assertIn('id="personalizationDetails"', INDEX_HTML)

    def test_duplicate_readiness_and_approval_ui_is_removed(self):
        for token in ('campaignReadiness', 'reviewedCheck', 'refreshBeforeReview', 'batchChip', 'healthChip', 'refreshButton'):
            self.assertNotIn(token, INDEX_HTML)
            self.assertNotIn(token, APP_JS)

    def test_sheet_viewer_and_expanded_tour_are_wired(self):
        self.assertIn('openSheetViewerButton', self.html)
        self.assertIn('sheetViewerDialog', self.html)
        self.assertIn('/api/imports/${state.importId}/rows', self.js)
        self.assertIn("title:'Four clear steps'", self.js)
        self.assertIn("title:'Preview personalized messages'", self.js)
        self.assertNotIn("view:'accounts'", self.js[self.js.index('const tourSteps=['):self.js.index('function startTour')])
        self.assertGreaterEqual(self.js.count("title:'"), 5)

    def test_first_run_tour_is_wired_and_replayable(self):
        self.assertIn('id="tourOverlay"', INDEX_HTML)
        self.assertIn('id="startTourButton"', INDEX_HTML)
        self.assertIn('const tourSteps=', APP_JS)
        self.assertIn('TOUR_STORAGE_KEY', APP_JS)
        self.assertIn("localStorage.getItem('maildesk-onboarded')", APP_JS)
        self.assertIn('requestAnimationFrame(startTour)', APP_JS)

    def test_wizard_does_not_restore_a_stale_step_without_runtime_state(self):
        self.assertNotIn('step:state.step', APP_JS)
        self.assertIn('if(data.sourceTab)setSourceTab(data.sourceTab);state.unlockedStep=1;setStep(1,{force:true});', APP_JS)
        self.assertNotIn('unlockedStep:state.unlockedStep', APP_JS)

    def test_send_confirmation_is_simple_and_mode_specific(self):
        self.assertIn("function openSendConfirmation()", APP_JS)
        self.assertIn("id=\"sendConfirmDialog\"", INDEX_HTML)
        self.assertIn("Confirm email delivery", INDEX_HTML)
        self.assertNotIn("batch_id[:8]", APP_JS)
        self.assertNotIn("reviewed:", APP_JS)

    def test_final_action_label_matches_delivery_mode(self):
        self.assertIn('Run dry test', APP_JS)
        self.assertIn('Open ${count} browser draft', APP_JS)
        self.assertIn('Create ${count} Gmail draft', APP_JS)
        self.assertIn('`Send ${count} ${plural}`', APP_JS)

    def test_delivery_blockers_explain_the_next_safe_action(self):
        self.assertIn('No Gmail accounts connected', APP_JS)
        self.assertIn('Connect Gmail to continue', APP_JS)
        self.assertIn('data-delivery-setup', APP_JS)
        self.assertIn('Choose a Gmail account…', APP_JS)
        self.assertIn('id="gmailAccountHelp"', INDEX_HTML)

    def test_default_recipient_flow_avoids_duplicate_worksheet_preview(self):
        self.assertIn("els.sheetPreviewWrap.classList.toggle('is-hidden',state.source?.source_type==='worksheet')", APP_JS)
        self.assertIn('function flushWorksheetAutosave()', APP_JS)
        self.assertIn("'Continue to write'", APP_JS)
        self.assertNotIn('id="recipientMappingDetails" open', INDEX_HTML)

    def test_error_messages_add_concrete_recovery_guidance(self):
        self.assertIn('function actionableError(message)', APP_JS)
        self.assertIn('Remove that {{field}} from the message', APP_JS)
        self.assertIn('open Accounts and connect Gmail first', APP_JS)
        self.assertIn('Rescan browsers in Accounts', APP_JS)

    def test_builtin_worksheet_and_quick_placeholder_insertion_are_wired(self):
        for token in (
            "worksheetSourcePane", "manualWorksheetName", "manualWorksheetTable",
            "addWorksheetColumnButton", "addWorksheetRowButton", "pasteWorksheetButton", "undoWorksheetButton",
            "worksheetPasteDialog", "worksheetPasteInput", "quickInsertColumn", "quickInsertFieldButton",
        ):
            self.assertIn(f'id="{token}"', INDEX_HTML)
        self.assertIn("/api/imports/worksheet", APP_JS)
        self.assertIn("function applyManualWorksheet", APP_JS)
        self.assertIn("function fillWorksheetRange", APP_JS)
        self.assertIn("function applyWorksheetPaste", APP_JS)
        self.assertIn("function insertQuickField", APP_JS)
        self.assertIn("function insertMappedPlaceholder", APP_JS)
        self.assertIn("Built-in worksheet", INDEX_HTML)
        self.assertIn("Paste from spreadsheet", INDEX_HTML)
        self.assertIn('aria-labelledby="worksheetPasteTitle"', INDEX_HTML)

    def test_guided_placeholder_builder_covers_source_fallback_and_insertion(self):
        for token in ('placeholderNameInput', 'placeholderSourceSelect', 'placeholderFallbackInput', 'placeholderTokenPreview', 'placeholderSamplePreview', 'placeholderInsertTarget', 'insertPlaceholderButton', 'insertConditionalButton', 'placeholderMappingSummary'):
            self.assertIn(f'id="{token}"', INDEX_HTML)
        self.assertIn('function insertPlaceholderFromBuilder()', APP_JS)
        self.assertIn('function insertConditionalFromBuilder()', APP_JS)
        self.assertIn('function setPlaceholderFallback(key,fallback)', APP_JS)
        self.assertIn('placeholderMappingLocked', APP_JS)
        self.assertIn("No column · use fallback only", APP_JS)
        self.assertIn('id="personalizationDetails"', INDEX_HTML)
        self.assertIn('els.personalizationDetails.open=true', APP_JS)

    def test_template_authoring_is_guided_and_previewable(self):
        for token in (
            "templateSaveStatus",
            "duplicateTemplateButton",
            "templateFillStatus",
            "placeholderTargetSelect",
            "templateSampleRowSelect",
            "templateSampleStatus",
            "templateSampleSubject",
            "templateSampleBody",
        ):
            self.assertIn(f'id="{token}"', INDEX_HTML)
        self.assertIn("function renderTemplateSample()", APP_JS)
        self.assertIn("function renderTemplateTextSample(", APP_JS)
        self.assertIn("function templateFieldReadiness(", APP_JS)
        self.assertIn("function insertIntoTemplateTarget(", APP_JS)

    def test_template_changes_save_automatically_with_undo(self):
        self.assertIn("templateDirty: false", APP_JS)
        self.assertIn("function scheduleTemplateAutosave()", APP_JS)
        self.assertIn("function undoTemplateChange()", APP_JS)
        self.assertIn('id="undoTemplateButton"', INDEX_HTML)
        self.assertNotIn('id="saveTemplateButton"', INDEX_HTML)
        self.assertIn("Saved automatically", APP_JS)

    def test_four_step_workflow_has_no_stale_step_five_jump(self):
        self.assertNotIn("setStep(5)", APP_JS)

    def test_placeholder_mapping_ui_is_wired_to_render_payload(self):
        self.assertIn('id="placeholderMappingList"', INDEX_HTML)
        self.assertIn('id="autoMapPlaceholdersButton"', INDEX_HTML)
        self.assertIn('templatePlaceholderInfo', APP_JS)
        self.assertIn('placeholder_mappings:Object.fromEntries', APP_JS)

    def test_live_sheet_summary_writes_to_registered_dom_element(self):
        self.assertIn("els.liveSheetSummary.textContent=", APP_JS)
        self.assertNotIn("state.liveSheetSummary.textContent=", APP_JS)

    def test_live_sheet_stays_beside_message_preview(self):
        self.assertIn('id="liveSheetCard"', INDEX_HTML)
        self.assertIn('id="liveSheetTable"', INDEX_HTML)
        self.assertIn('function renderLiveSheet()', APP_JS)
        self.assertIn("findIndex(message=>String(message.row_number)===String(row._row))", APP_JS)


    def test_google_oauth_setup_is_reusable_and_has_health_controls(self):
        for token in ("connectGoogleButton", "oauthFileLabel", "googleOauthStatus"):
            self.assertIn(f'id="{token}"', INDEX_HTML)
        self.assertIn("/api/oauth/google/client", APP_JS)
        self.assertIn("function reconnectGoogleAccount(email)", APP_JS)
        self.assertIn("function checkGoogleAccount(email)", APP_JS)
        self.assertIn("Forget saved client", APP_JS)
        self.assertIn("does not revoke the Google authorization", APP_JS)
        self.assertIn("els.oauthFileLabel.addEventListener('click',()=>els.oauthFile.click())", APP_JS)
        self.assertIn('id="attachmentFileButton"', INDEX_HTML)

    def test_browser_sender_setup_prefers_detected_accounts(self):
        self.assertIn('id="detectedBrowserAccounts"', INDEX_HTML)
        self.assertIn('id="rescanBrowserProfilesButton"', INDEX_HTML)
        self.assertIn('/api/browser-profiles?refresh=true', APP_JS)
        self.assertIn('p?.gmail_accounts||[]', APP_JS)
        self.assertIn('Can’t see the account?', INDEX_HTML)

    def test_oauth2_setup_is_explicit_and_sheets_scope_is_opt_in(self):
        self.assertIn('Google OAuth 2.0', INDEX_HTML)
        self.assertIn('OAuth 2.1-compatible setup', APP_JS)
        self.assertIn('maildesk-google-oauth-complete', APP_JS)
        self.assertIn("window.addEventListener('message',handleGoogleOauthMessage)", APP_JS)
        sheets = re.search(r'<input id="includeSheetsScope"[^>]*>', INDEX_HTML)
        self.assertIsNotNone(sheets)
        self.assertNotIn('checked', sheets.group(0))
        self.assertIn('only needed for Google Sheets recipient lists', INDEX_HTML)

    def test_primary_navigation_and_dynamic_states_are_announced(self):
        self.assertIn('class="skip-link" href="#mainContent"', INDEX_HTML)
        self.assertIn('id="mainContent"', INDEX_HTML)
        self.assertIn('class="nav-icon" aria-hidden="true"', INDEX_HTML)
        self.assertIn('class="source-tab is-active" data-source-tab="worksheet" aria-pressed="true"', INDEX_HTML)
        self.assertIn('class="editor-tab is-active" data-editor="plain" aria-pressed="true"', INDEX_HTML)
        self.assertIn('id="busyOverlay" class="busy-overlay is-hidden" role="status" aria-live="polite" aria-hidden="true"', INDEX_HTML)
        self.assertIn("setAttribute('aria-pressed',String(active))", APP_JS)
        self.assertIn("setAttribute('aria-current','page')", APP_JS)
        self.assertIn("setAttribute('aria-hidden',String(!on))", APP_JS)

    def test_visual_review_e2e_has_stable_product_selectors(self):
        self.assertIn('data-testid="main-content"', INDEX_HTML)
        self.assertIn('data-testid="nav-accounts"', INDEX_HTML)
        self.assertIn('data-testid="gmail-oauth-setup"', INDEX_HTML)

    def test_tour_keeps_keyboard_focus_inside_dialog(self):
        self.assertIn('function handleTourKeydown(event)', APP_JS)
        self.assertIn("event.key!=='Tab'", APP_JS)
        self.assertIn("event.preventDefault()", APP_JS)


if __name__ == "__main__":
    unittest.main()
