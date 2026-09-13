# Architecture

MailDesk is intentionally a **modular local monolith**. There is one desktop process, one loopback HTTP service, one SQLite database and explicit adapters for file spreadsheets, Google Sheets, Chromium profiles and Gmail.

## Boundaries

```text
Desktop shell (pywebview)
        │
        ▼
FastAPI loopback application
 ├─ Template/render engine
 ├─ Spreadsheet adapter (CSV/XLSX)
 ├─ Google Sheets snapshot adapter
 ├─ Browser route adapter
 ├─ Gmail OAuth/API adapter
 ├─ Persistent campaign queue
 └─ SQLite/secret storage
        │
        ├─ Local DB / attachments / backups
        ├─ Gmail API (optional)
        ├─ Google Sheets API (optional)
        └─ Local Chromium browser (optional)
```

No queue broker, cloud database, frontend build system, service mesh, or remote application backend is required.

## Source modules

- `main.py` — API contract, validation, campaign worker/scheduler and composition.
- `storage.py` — migrations, encrypted credential persistence, templates, sender routes, attachments, history and queue state.
- `template_engine.py` — non-executable placeholder/default/conditional rendering and fingerprints.
- `sheet_reader.py` — CSV/XLSX parsing, header detection and mapping suggestions.
- `gmail_client.py` — OAuth PKCE, Gmail MIME/API and Google Sheets HTTP operations.
- `google_sheets.py` — converts a live Google spreadsheet into a local XLSX snapshot.
- `browser_profiles.py` — Chromium discovery plus explicit Gmail `/u/N/` routing.
- `desktop.py` — native window, single-instance lock and embedded local server.

## Why a persistent local queue

Directly looping over a batch from a request handler made pause/resume, scheduling and crash recovery impossible. Queue rows now exist before external side effects occur. A process restart converts `Running` to `Paused`, ensuring the app never guesses whether the user wanted a batch to continue.

## Browser identity model

`browser_id + profile_dir` selects the Chromium profile. `gmail_slot` selects the Gmail session account inside it. `expected_email` is the human identity. A recent verification binds the current session route to that expected email for a bounded period.

The numeric Gmail slot is routing metadata, not durable account identity.

## Google Sheets consistency model

The app never sends directly from changing live rows. It snapshots the current Google Sheet into a local XLSX, then runs the same mapping/render/review path as a local workbook. The user may refresh the snapshot; refreshing invalidates the current rendered review.

This prevents a live Sheet changing silently after the user reviewed the campaign.
