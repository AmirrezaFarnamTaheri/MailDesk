# MailDesk

MailDesk is a **local-first desktop mail-merge application** for preparing reusable email templates, filling them from Excel/CSV/Google Sheets, reviewing every generated message, and then creating browser drafts, Gmail API drafts, or sending through Gmail with explicit safety gates.

Version: **0.2.0**

## What changed in 0.2

The original PowerShell workflow has been generalized into a product rather than wrapped as-is. This release addresses the full next-stage backlog:

1. **Desktop productionization** — native pywebview window, first-run guide, single-instance guard, persistent UI preferences, version/about endpoint, database backups, PyInstaller + Inno Setup packaging, optional Authenticode signing.
2. **Richer templates** — plain text + HTML, signatures, snippets, defaults (`{{Name|there}}`), conditionals (`{{#if Link}}…{{/if}}`), attachments, and Content-ID inline images.
3. **Smarter spreadsheet handling** — Excel/CSV drag-and-drop, header detection, automatic column suggestions, recipient/name/Cc/Bcc/attachment mapping, filters, row selection, campaign-only cell edits, duplicate-recipient warnings, large-sheet guardrails.
4. **First-class multi-account routing** — Gmail API accounts are separate from browser routes. Browser routes explicitly store **browser + browser profile + Gmail `/u/N/` slot + expected email**.
5. **Persistent send queue** — each message has a durable state and campaign ID; campaigns can be paused, resumed, cancelled, inspected, throttled, and failed items retried. Interrupted running campaigns come back **Paused**, never silently resumed.
6. **Stronger safety** — true dry run, exact batch fingerprint, sender verification, duplicate protection, attachment validation/size limits, blocked executable attachments, configurable batch cap, and typed confirmation for real sends.
7. **Scheduling + campaign history** — campaigns may be scheduled, operation history is queryable/exportable, and a local audit ledger records every attempt and remote ID.
8. **Five-step GUI** — Recipients → Template → Personalization → Delivery → Review & queue, with a persistent live message-review pane and per-message edits.
9. **Google Sheets snapshots** — connect with read-only Sheets scope, load a spreadsheet by URL/ID, refresh its snapshot, then review the snapshot before processing.
10. **Hardening/distribution** — Windows/Linux CI, Python 3.11/3.13 coverage, JavaScript syntax checks, migration backups, token/error redaction, malformed-workbook tests, RTL/Unicode tests, large-sheet tests, queue restart tests, and installer artifacts.

## The important browser-account model

A Chromium **browser profile** and a Gmail **account slot** are different things. A single Chrome profile may have several Gmail accounts:

```text
Chrome / Profile 1
├── Gmail /u/0/ → personal@example.com
└── Gmail /u/1/ → work@example.com
```

MailDesk therefore saves each browser sender as:

```text
Browser:         Chrome
Browser profile: Profile 1
Gmail slot:      1
Expected email:  work@example.com
Label:           Work Gmail
```

Browser drafts are opened using the exact slot URL, e.g. `https://mail.google.com/mail/u/1/?view=cm...`.

Because Gmail slot numbers depend on the current browser account session, MailDesk **does not pretend it can permanently infer which email owns `/u/1/`**. Before browser drafts can run, the app opens the configured `/u/N/#inbox` and requires the user to confirm that the visible account is the expected email. That verification expires after 30 minutes.

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
6. In **Accounts**, choose **Connect Google** and select the JSON.
7. Leave “Google Sheets read-only” checked if you want live Sheet snapshots.

Scopes used:

- Gmail compose: `https://www.googleapis.com/auth/gmail.compose`
- Google Sheets read-only: `https://www.googleapis.com/auth/spreadsheets.readonly`

MailDesk does not request general Gmail read access or Google Drive access.

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

Scheduling is local. The machine and MailDesk must be running at the scheduled time. This is intentional: no server/cloud component is introduced just to schedule email.

For a scheduled **browser** campaign, Gmail-route verification may have expired by execution time. In that case the campaign pauses until the route is re-verified and resumed.

## Real-send confirmation

For `N` messages, sending requires:

1. zero blocking validation errors;
2. the final-review checkbox;
3. a connected and re-verified Gmail sender account;
4. typing:

```text
SEND N ABCD1234
```

where `ABCD1234` is derived from the current batch fingerprint. If any reviewed message changes, the batch ID changes.

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
dist/installer/MailDesk-0.2.0-Setup.exe
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

## Test

```bash
python -m unittest discover -s tests -v
node --check mailmerge_app/static/app.js
python -m compileall -q mailmerge_app
```

The suite covers template safety, Unicode/RTL, spreadsheet parsing, mapping suggestions, large workbooks, OAuth/PKCE scopes, MIME HTML/attachments, Gmail account slots, persistent queue behavior, restart pausing, malformed uploads, executable attachment blocking, and dry-run execution.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/USER-GUIDE.md](docs/USER-GUIDE.md).
