# MailDesk

MailDesk is a **local-first desktop mail-merge application** for preparing reusable email templates, filling them from Excel/CSV/Google Sheets, reviewing every generated message, and then creating browser drafts, Gmail API drafts, or sending through Gmail.

Version: **0.4.0**

## What changed in 0.4

The original PowerShell workflow has been generalized into a product rather than wrapped as-is. This release addresses the full next-stage backlog:

1. **Desktop productionization** — native pywebview window, first-run guided tour, single-instance guard, persistent UI preferences, version/about endpoint, database backups, PyInstaller + Inno Setup packaging, optional Authenticode signing.
2. **Guided reusable templates** — plain text + HTML, signatures, snippets, defaults (`{{Name|there}}`), conditionals (`{{#if Link}}…{{/if}}`), attachments, Content-ID inline images, spreadsheet-field insertion, mapping checks, unsaved-change protection, duplication, and a live example recipient preview.
3. **Smarter recipient data handling** — a built-in editable worksheet with rectangular clipboard paste, plus Excel/CSV drag-and-drop and Google Sheets snapshots, header detection, automatic column suggestions, mappings, filters, row selection, duplicate-recipient warnings, and large-sheet guardrails.
4. **First-class multi-account support** — Gmail API accounts are separate from browser login accounts. Google Desktop OAuth setup is reusable across account connections, while each Gmail account keeps its own encrypted token/client pair. Browser accounts store the browser profile, account index and expected email.
5. **Persistent send queue** — each message has a durable state and campaign ID; campaigns can be paused, resumed, cancelled, inspected, throttled, and failed items retried. Interrupted running campaigns come back **Paused**, never silently resumed.
6. **Delivery controls** — dry run, internal batch-integrity checks, account verification, duplicate protection, attachment limits, blocked executable attachments, configurable batch cap, and typed confirmation for live sends.
7. **Scheduling + campaign history** — campaigns may be scheduled, operation history is queryable/exportable, and a local audit ledger records every attempt and remote ID.
8. **Four-step GUI** — Recipients → Write → Preview → Send, with progressive disclosure, guided template filling, message review, and per-message edits.
9. **Google Sheets snapshots** — connect with read-only Sheets scope, load a spreadsheet by URL/ID, refresh its snapshot, then review the snapshot before processing.
10. **Validation/distribution** — Windows/Linux CI, Python 3.11/3.13 coverage, JavaScript syntax checks, a Playwright visual-review journey with uploaded screenshots, migration backups, token/error redaction, malformed-workbook tests, RTL/Unicode tests, large-sheet tests, queue restart tests, and installer artifacts.

## Browser accounts

A Chromium **browser profile** and a Gmail **account slot** are different things. A single Chrome profile may have several Gmail accounts:

```text
Chrome / Profile 1
├── Gmail /u/0/ → personal@example.com
└── Gmail /u/1/ → work@example.com
```

MailDesk saves each browser account as:

```text
Browser:         Chrome
Browser profile: Profile 1
Account index:   1
Expected email:  work@example.com
Label:           Work Gmail
```

Browser drafts are opened using the exact slot URL, e.g. `https://mail.google.com/mail/u/1/?view=cm...`.

Gmail account indexes depend on the current signed-in account order. Before browser drafts run, MailDesk opens the configured account and asks you to confirm that the visible email matches the saved browser account. Verification expires after 30 minutes.

## Run from source

### Windows

Requirements: Python **3.11+**.

Double-click:

```text
run.bat
```

or:

```powershell
./run.ps1
```

First launch creates `.venv`, installs dependencies, then opens the native desktop window. If pywebview cannot be used, the local server can still be run with:

```powershell
.venv\Scripts\python.exe -m mailmerge_app.main
```

### Linux/macOS development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m mailmerge_app.main
```

The local service binds only to `127.0.0.1:8765`.

## Google setup

Browser-draft and dry-run modes require **no Google Cloud OAuth setup**.

For Gmail API drafts/sends and Google Sheets:

1. Create a Google Cloud project.
2. Enable the **Gmail API** and, if desired, **Google Sheets API**.
3. Configure an OAuth consent screen.
4. Create an OAuth Client ID of type **Desktop app**.
5. Download its JSON.
6. In **Accounts → Gmail accounts**, choose **Set up & connect** and select the JSON once.
7. Complete Google sign-in in the dedicated popup. Google can reuse the account already signed in to your local browser; on completion MailDesk closes the popup and refreshes the account list. MailDesk stores the Desktop client encrypted on this device, so later accounts can use **Connect Gmail** without selecting the JSON again.
8. Leave read-only Google Sheets access enabled if you want Sheet snapshots.

Each connected account now exposes **Check** and **Reconnect** actions. Reconnect is locked to the expected email address, so authorizing the wrong Google account cannot silently replace another account. A local **Disconnect** only removes MailDesk's stored credential; the API also exposes explicit revocation when a full Google authorization revoke is required.

Scopes used:

- Gmail compose: `https://www.googleapis.com/auth/gmail.compose`
- Google Sheets read-only: `https://www.googleapis.com/auth/spreadsheets.readonly`

The desktop client follows the OAuth 2.1 profile: authorization code + PKCE (S256), a bounded single-use state, and the exact local loopback callback. It deliberately does **not** support implicit or password grants, switch to legacy password authentication, embed an IMAP/SMTP proxy, request `https://mail.google.com/`, request general Gmail read access, or request Google Drive access. Gmail API delivery remains the default because it provides the app's required draft/send behavior with a narrower permission set.

See `docs/OAUTH-INTEGRATION.md` for how the supplied OAuth/Gmail reference projects were evaluated and integrated.

## Template syntax

Supported syntax is deliberately small and non-executable:

```text
Hello {{Name}}
Hello {{Name|there}}
Row {{_row}}
Date {{_today}}

{{#if MeetingLink}}
Join here: {{MeetingLink}}
{{/if}}
```

There is no expression evaluation, arbitrary code, function invocation, or template-side file access.

### HTML and inline images

Upload an image under **Attachments**, then choose **Inline** next to it while editing the HTML message. The editor inserts a `cid:<attachment-id>` reference. Gmail API delivery converts it into a MIME Content-ID inline image.

Browser compose URLs cannot attach files or inject arbitrary HTML; MailDesk therefore blocks browser-mode campaigns that contain attachments rather than silently dropping them.

## Queue semantics

Every campaign and row is persisted in SQLite.

Message states include:

```text
Pending → Success
        → Failed → Retry → Success/Failed
        → Skipped
```

Campaign states include:

```text
Queued / Scheduled → Running → Completed / CompletedWithErrors
                         ↘ Paused
                         ↘ Cancelled
```

A process restart converts an interrupted `Running` campaign to `Paused`. The user must explicitly resume it.

### Scheduling

Scheduling is local. MailDesk and the machine must be running at the scheduled time.

For a scheduled **browser** campaign, account verification may expire before execution. In that case the campaign pauses until the account is verified again and resumed.

## Real-send confirmation

For `N` messages, live sending requires a confirmation dialog that shows the recipient count and selected Gmail account. Choose **Send emails** in that dialog to continue; cancelling leaves the campaign unchanged.

Live sending still requires zero blocking validation errors and a connected Gmail account.

MailDesk still verifies the rendered batch internally before processing it; the internal fingerprint is not exposed as a user confirmation step.

## Local data and secrets

Default Windows storage:

```text
%LOCALAPPDATA%\MailDesk\
```

Contains the SQLite database, imports, attachments, backups and local secret material.

- Windows uses **DPAPI** for stored Google credentials.
- Non-Windows development uses a local Fernet key with restricted file permissions where supported.
- Startup creates bounded database migration backups.
- Logs/history never intentionally store access tokens, refresh tokens, client secrets, or message bodies.

See [docs/SECURITY.md](docs/SECURITY.md).

## Build a Windows installer

Install Python 3.11 and Inno Setup 6, then:

```powershell
./packaging/build-windows.ps1
```

Outputs:

```text
dist/MailDesk.exe
dist/installer/MailDesk-0.4.0-Setup.exe
```

Optional signing:

```powershell
$env:MAILDESK_SIGN_CERT_PFX='C:\path\certificate.pfx'
$env:MAILDESK_SIGN_CERT_PASSWORD='...'
./packaging/build-windows.ps1
```

### GitHub Actions Windows build

The dedicated workflow at `.github/workflows/build-windows.yml` builds the final Windows artifacts on `windows-latest`. It runs on:

- manual **Run workflow** (`workflow_dispatch`);
- pushes to `main` or `master`;
- version tags matching `v*`.

The workflow compiles and tests the Python code, checks the frontend JavaScript, builds the PyInstaller executable, actually runs the frozen GUI executable in a headless marker-file startup smoke test, builds the Inno Setup installer, generates SHA-256 checksums, and uploads two downloadable GitHub Actions artifacts:

```text
MailDesk-Windows-EXE-<commit>
MailDesk-Windows-Installer-<commit>
```

The standalone artifact contains `MailDesk.exe` plus `SHA256SUMS.txt`; the installer artifact contains the setup executable plus the same checksum manifest.

Optional Authenticode signing uses these repository secrets:

```text
MAILMERGE_SIGN_CERT_BASE64
MAILMERGE_SIGN_CERT_PASSWORD
```

`MAILMERGE_SIGN_CERT_BASE64` must contain the base64-encoded PFX bytes. If the secrets are absent, the workflow still produces unsigned artifacts.

### CI visual review

The standard CI workflow also runs a broad Playwright journey on Ubuntu. It starts the real local application, reviews **Write**, **Preview**, **Send**, **Campaigns**, **Activity**, **Accounts**, the built-in worksheet, a mocked OAuth consent popup, and both delivery configurations: a connected **Gmail API** account and a verified local **browser-drafts** account. It uploads the screenshot set and server log as a `MailDesk-Visual-Review-<commit>` artifact. The tour is suppressed only for this stable visual baseline; it remains covered by frontend regression tests. This is an approval aid for UI changes, while the browser assertions make it a genuine end-to-end gate.

## Test

```bash
python -m unittest discover -s tests -v
pytest -q
node --check mailmerge_app/static/app.js
python -m compileall -q mailmerge_app
```

To capture the running desktop interface in a repeatable browser viewport:

```bash
python -m playwright install chromium
python scripts/capture_screenshot.py --full-page
python scripts/visual_review_e2e.py --output artifacts/visual-review/accounts.png
```

The suite covers template safety, Unicode/RTL, spreadsheet parsing, mapping suggestions, large workbooks, OAuth/PKCE scopes, MIME HTML/attachments, Gmail account slots, persistent queue behavior, restart pausing, malformed uploads, executable attachment blocking, and dry-run execution.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/USER-GUIDE.md](docs/USER-GUIDE.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
