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
 ├─ OAuth 2.0 client lifecycle + PKCE adapter
 ├─ Gmail API adapter
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
- `oauth_client.py` — provider-neutral OAuth 2.0 authorization-code/PKCE, refresh-token rotation, health metadata and revocation primitives.
- `gmail_client.py` — Google-specific OAuth bindings plus Gmail MIME/API and Google Sheets HTTP operations.
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

## OAuth client model

The Google Desktop OAuth client is stored once in the encrypted local secret store (`oauth_clients`) and reused for later account connections. Each Gmail account still stores its own encrypted token and the client configuration that issued it, so existing accounts continue to refresh correctly even if the reusable default client is later changed or forgotten.

Authorization sessions are one-time, in-memory, PKCE-bound records with a ten-minute lifetime. Reconnect sessions also carry the expected email address; the callback refuses to overwrite the account if Google returns a different identity. Refresh responses accept refresh-token rotation rather than assuming refresh tokens are immutable.

MailDesk remains an OAuth **client**, not an authorization server or protocol proxy. The supplied authorization-server and IMAP/POP/SMTP proxy projects were used as design references only where their client-side lifecycle patterns fit this architecture. See `OAUTH-INTEGRATION.md`.
