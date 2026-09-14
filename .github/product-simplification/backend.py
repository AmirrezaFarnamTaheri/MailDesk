from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 exact match, found {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement: str, label: str, flags: int = 0) -> str:
    output, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 regex match, found {count}")
    return output


main = read("mailmerge_app/main.py")
main = replace_once(main, "BROWSER_VERIFICATION_MINUTES = 30\n", "", "remove browser verification timeout")
main = replace_once(
    main,
    '        "browser_verification_minutes": BROWSER_VERIFICATION_MINUTES,\n',
    "",
    "remove browser verification timeout from about",
)
main = sub_once(
    main,
    r"class TemplatePayload\(BaseModel\):\n.*?\n\nclass SnippetPayload\(BaseModel\):",
    '''class TemplatePayload(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=200_000)
    body_html: str = Field(default="", max_length=400_000)
    signature_html: str = Field(default="", max_length=100_000)
    cc_template: str = Field(default="", max_length=4_000)
    bcc_template: str = Field(default="", max_length=4_000)


class SnippetPayload(BaseModel):''',
    "simplify template payload",
    re.S,
)
main = replace_once(
    main,
    '    selected_rows: list[str] = Field(default_factory=list, max_length=100_000)\n',
    '    selected_rows: list[str] | None = Field(default=None, max_length=100_000)\n',
    "make row selection explicit",
)
main = replace_once(
    main,
    '    reviewed: bool = False\n    confirm_text: str = Field(default="", max_length=200)\n',
    '    confirm_send: bool = False\n',
    "simplify send confirmation contract",
)
main = replace_once(
    main,
    '    _validate_attachment_ids(payload.attachment_ids)\n    return store.save_template(payload.model_dump())\n',
    '    return store.save_template(payload.model_dump())\n',
    "templates no longer own attachments",
)
main = replace_once(
    main,
    '    if payload.selected_rows:\n        selected = set(payload.selected_rows)\n        rows = [row for row in rows if row.get("_row") in selected]\n',
    '    if payload.selected_rows is not None:\n        selected = set(payload.selected_rows)\n        rows = [row for row in rows if row.get("_row") in selected]\n',
    "render explicit row selection",
)
main = replace_once(
    main,
    '''    if payload.mode == "send":
        expected = f"SEND {len(payload.messages)} {payload.batch_id[:8].upper()}"
        if not payload.reviewed or payload.confirm_text.strip() != expected:
            raise HTTPException(400, f"Sending requires review and typing exactly: {expected}")
        if not payload.account:
            raise HTTPException(400, "Select a connected Gmail account.")
''',
    '''    if payload.mode == "send":
        if not payload.confirm_send:
            raise HTTPException(400, "Confirm the send before processing.")
        if not payload.account:
            raise HTTPException(400, "Select a connected Gmail account.")
''',
    "replace typed send token",
)
main = main.replace("_require_fresh_browser_sender", "_require_verified_browser_sender")
main = sub_once(
    main,
    r"def _require_verified_browser_sender\(sender_id: str\) -> dict\[str, Any\]:\n.*?\n    return sender\n",
    '''def _require_verified_browser_sender(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(400, "Select a saved browser sender route.")
    if not sender.get("verified_at"):
        raise HTTPException(409, f"Verify {sender['expected_email']} for this browser route before opening drafts.")
    _profile_for_sender(sender)
    return sender
''',
    "simplify browser verification",
    re.S,
)
write("mailmerge_app/main.py", main)

storage = read("mailmerge_app/storage.py")
storage = sub_once(
    storage,
    r"    def _seed\(self, db: sqlite3.Connection\) -> None:\n.*?\n    # ---------- templates / snippets ----------",
    '''    def _seed(self, db: sqlite3.Connection) -> None:
        now = _utc_now()

        # Retire untouched built-in examples that were tied to a particular use case.
        db.execute(
            "DELETE FROM templates WHERE id='interview-fa' AND name='Interview schedule (Persian)' AND updated_at=created_at"
        )

        # Existing installations keep user-edited templates. Only the untouched
        # starter template is generalized into neutral reusable message content.
        db.execute(
            """
            UPDATE templates
            SET name=?, subject=?, body=?, tags='', attachment_ids='[]',
                default_account='', default_browser_sender_id='', updated_at=?
            WHERE id='simple-outreach' AND name='Simple outreach' AND updated_at=created_at
            """,
            (
                "General message",
                "Hello",
                "Hello,\\n\\nWrite your message here.\\n\\nBest,",
                now,
            ),
        )

        if db.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
            db.execute(
                """INSERT INTO templates(id,name,subject,body,cc_template,bcc_template,body_html,signature_html,attachment_ids,tags,default_account,default_browser_sender_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "general-message", "General message", "Hello",
                    "Hello,\\n\\nWrite your message here.\\n\\nBest,",
                    "", "", "", "", "[]", "", "", "", now, now,
                ),
            )
        db.execute(
            "INSERT OR IGNORE INTO snippets(id,name,content,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("follow-up", "Follow-up line", "Just following up on the message below.", now, now),
        )

    # ---------- templates / snippets ----------''',
    "generalize starter templates",
    re.S,
)
write("mailmerge_app/storage.py", storage)

# Update API tests for explicit row selection and the simpler send confirmation.
test_api = read("tests/test_api.py")
test_api = test_api.replace('"selected_rows":[],', '"selected_rows":None,')
test_api = test_api.replace('"selected_rows": [],', '"selected_rows": None,')
test_api = sub_once(
    test_api,
    r"    def test_send_requires_exact_batch_confirmation_before_account_lookup\(self\):\n.*?\n\n    def test_campaign_api_rejects_blank_recipient_even_if_client_claims_no_errors",
    '''    def test_send_requires_explicit_confirmation_before_account_lookup(self):
        messages = [self._message()]
        batch_id = self._batch_id(messages)
        response = self.client.post('/api/campaigns', json={
            "name":"Send", "mode":"send", "account":"missing@example.com",
            "batch_id":batch_id, "messages":messages, "skip_duplicates":True,
            "throttle_ms":0, "scheduled_at":"", "confirm_send":False,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Confirm the send", response.json()["detail"])

    def test_campaign_api_rejects_blank_recipient_even_if_client_claims_no_errors''',
    "update send confirmation API test",
    re.S,
)
insert = '''
    def test_empty_row_selection_means_no_rows(self):
        upload = self.client.post(
            "/api/imports",
            files={"file": ("valid.xlsx", self._valid_workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ).json()
        response = self.client.post("/api/render", json={
            "import_id": upload["import_id"], "sheet": "Contacts", "to_column": "Email",
            "subject": "Hello", "body": "Body", "selected_rows": [],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 0)

'''
marker = "    def test_malformed_xlsx_is_rejected(self):\n"
if marker not in test_api:
    raise RuntimeError("could not insert zero-selection API test")
test_api = test_api.replace(marker, insert + marker, 1)
write("tests/test_api.py", test_api)

# Keep docs aligned with the simpler product contract.
user_guide = '''# User Guide

MailDesk uses four steps: **Recipients → Message → Check → Delivery**. The first-run tour walks through the same flow in the app.

## 1. Recipients

Choose Excel/CSV or load a Google Sheet. Confirm the worksheet and recipient email column. Name, Cc, Bcc, filtering, sorting and limits are optional.

The preview supports row selection and campaign-only cell edits. Your original spreadsheet is not changed.

## 2. Message

Choose a saved template or write a message. Templates store reusable message content only; the current sender, recipient list and attachments stay with the campaign so the same template can be reused anywhere.

Placeholders come from the loaded spreadsheet. You can also use snippets, optional HTML, signatures and attachments.

## 3. Check

Choose **Check messages** to generate the personalized result. Rows with blocking errors must be fixed before delivery. Use the preview on the right to inspect or edit individual messages.

## 4. Delivery

Choose what happens next:

- **Dry run** — process locally without creating drafts or sending.
- **Browser compose** — open Gmail compose windows in a saved browser profile.
- **Gmail drafts** — create drafts through the connected Gmail account.
- **Send email** — send through the connected Gmail account.

You can set a campaign name, schedule, pacing and duplicate handling. The final button states the exact action and message count. Sending asks for one explicit confirmation before the campaign is queued.

## Queue

Queue shows progress and lets you pause, resume, retry failed items, cancel work or inspect row outcomes. If Gmail returns an uncertain result, MailDesk pauses that item for a human decision instead of guessing or replaying it.

## Browser routes

Under **Senders**, save the browser profile, Gmail slot and expected email once, then verify the route. Verification remains valid until that route is edited; changing its profile, slot or email requires verification again. MailDesk still checks that the configured browser profile exists before use.
'''
write("docs/USER-GUIDE.md", user_guide)

security = read("docs/SECURITY.md")
security = security.replace(
    "Browser mode cannot securely introspect Gmail's internal account-slot assignment without browser automation/session access. Instead it opens the exact configured `/u/N/#inbox` and requires human confirmation that the visible account is the expected email. Verification expires after 30 minutes.",
    "Browser mode cannot securely introspect Gmail's internal account-slot assignment without browser automation/session access. When a route is configured, MailDesk opens the selected Gmail account slot and asks for one human verification. Editing the profile, slot or expected email clears that verification; profile availability is checked again before use.",
)
security = security.replace(
    "The rendering layer identifies invalid recipients, unresolved placeholders, missing attachments and other blocking errors. Real send additionally requires a final review checkbox and exact batch-bound confirmation text.",
    "The rendering layer identifies invalid recipients, unresolved placeholders, missing attachments and other blocking errors. The server recomputes the batch fingerprint before queueing, and a real send requires one explicit send confirmation from the current UI.",
)
write("docs/SECURITY.md", security)

architecture = read("docs/ARCHITECTURE.md")
architecture = architecture.replace(
    "`browser_id + profile_dir` selects the Chromium profile. `gmail_slot` selects the Gmail session account inside it. `expected_email` is the human identity. A recent verification binds the current session route to that expected email for a bounded period.\n\nThe numeric Gmail slot is routing metadata, not durable account identity.",
    "`browser_id + profile_dir` selects the Chromium profile. `gmail_slot` selects the Gmail session account inside it. `expected_email` is the human identity. A human verification binds that route to the expected email and remains valid until the route configuration changes.\n\nThe numeric Gmail slot is routing metadata, not durable account identity, and the browser profile must still exist when the route is used.",
)
write("docs/ARCHITECTURE.md", architecture)

readme = read("README.md")
replacements = {
    "MailDesk is a **local-first desktop mail-merge application** for preparing reusable email templates, filling them from Excel/CSV/Google Sheets, reviewing every generated message, and then creating browser drafts, Gmail API drafts, or sending through Gmail with explicit safety gates.":
        "MailDesk is a **local-first desktop mail-merge application** for preparing reusable email templates, filling them from Excel/CSV/Google Sheets, reviewing generated messages, and then running locally, opening browser drafts, creating Gmail drafts, or sending through Gmail.",
    "Version: **0.2.0**": "Version: **0.2.1**",
    "native pywebview window, first-run guide, single-instance guard": "native pywebview window, first-run guided tour, single-instance guard",
    "true dry run, exact batch fingerprint, sender verification, duplicate protection, attachment validation/size limits, blocked executable attachments, configurable batch cap, and typed confirmation for real sends.":
        "true dry run, exact batch fingerprint, sender verification, duplicate protection, attachment validation/size limits, blocked executable attachments, configurable batch cap, and one explicit confirmation for real sends.",
    "**Five-step GUI** — Recipients → Template → Personalization → Delivery → Review & queue, with a persistent live message-review pane and per-message edits.":
        "**Four-step GUI** — Recipients → Message → Check → Delivery, with a first-run tour and a persistent live message-review pane.",
    "That verification expires after 30 minutes.": "Editing the saved route clears verification; otherwise it remains valid while the configured browser profile is available.",
    "For a scheduled **browser** campaign, Gmail-route verification may have expired by execution time. In that case the campaign pauses until the route is re-verified and resumed.\n":
        "For a scheduled **browser** campaign, MailDesk still checks that the saved browser profile and route are available when execution begins.\n",
    "dist/installer/MailDesk-0.2.0-Setup.exe": "dist/installer/MailDesk-0.2.1-Setup.exe",
}
for old, new in replacements.items():
    if old not in readme:
        raise RuntimeError(f"README text not found: {old[:70]}")
    readme = readme.replace(old, new, 1)
readme = sub_once(
    readme,
    r"## Real-send confirmation\n.*?\n## Local data and secrets",
    '''## Real-send confirmation

MailDesk does not ask users to copy a batch hash or complete a second review ritual. Blocking validation, batch integrity and sender checks are enforced by the application and server. When **Send email** is selected, the final action asks for one explicit confirmation with the current message count and sender before queueing.

## Local data and secrets''',
    "simplify README send confirmation",
    re.S,
)
write("README.md", readme)

print("backend/data/docs simplification applied")
