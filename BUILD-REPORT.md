# MailDesk 0.3.1 — Integration Report

## Current implementation status

| Area | Status | Delivered |
|---|---|---|
| Desktop shell | Done | pywebview desktop shell, loopback FastAPI service, single-instance lock, packaging and installer workflow |
| Guided templates | Done | reusable templates, spreadsheet-field insertion, fallback values, mapping health, unsaved-change protection, duplication and live sample recipient preview |
| Spreadsheet workflow | Done | XLSX/CSV/Google Sheets snapshots, header detection, mappings, filters, row selection and preview |
| Gmail OAuth | Done | OAuth 2.1-compatible authorization code + PKCE (S256), canonical 127.0.0.1 loopback callback, local-browser sign-in popup handoff, single-use bounded state sessions, encrypted per-account tokens/clients, reusable encrypted Desktop OAuth client, token refresh/rotation, account health checks, reconnect identity binding and explicit revoke endpoint |
| Browser senders | Done | Chromium profile/account discovery, `/u/N/` routing and time-bounded human verification |
| Gmail delivery | Done | Gmail API draft/send, MIME HTML/attachments/CID images, exact-account verification and uncertain-outcome handling |
| Queue/scheduling | Done | durable queue, pause/resume/cancel/retry, scheduling, restart-to-paused recovery and duplicate protection |
| Audit/history | Done | per-operation results, remote IDs, CSV export and campaign inspection |
| Safety | Done | dry run, send confirmation, scope checks, attachment policy, local-origin guard, secret redaction and migration backups |
| CI visual review | Done | Playwright starts the real loopback service, opens Senders, asserts Gmail OAuth/browser sender controls, and uploads a review screenshot plus server log |
| OAuth reference integration | Done | compatible lifecycle patterns merged; obsolete OAuth 1.0, Python 2 password/IMAP code, embedded OAuth server and IMAP/POP/SMTP proxy deliberately not vendored |

## OAuth/Gmail reference integration

The supplied `email-oauth2-proxy`, `example-oauth2-server`, `python-oauth2`, and `gmail` repositories were reviewed against MailDesk's architecture. The resulting implementation is documented in `docs/OAUTH-INTEGRATION.md`.

Key outcomes:

- reusable provider-neutral OAuth lifecycle primitives live in `mailmerge_app/oauth_client.py`;
- Google Desktop client setup is encrypted and reusable instead of requiring a JSON upload for every Gmail account;
- refresh-token rotation is preserved correctly;
- reconnect callbacks are bound to the intended Gmail identity;
- health/reconnect/revocation are explicit lifecycle actions;
- Gmail API compose remains the production transport, avoiding unnecessary `https://mail.google.com/` scope expansion and legacy password authentication.

## Verification performed

- `pytest -q` — **128 passed**.
- `python -m compileall -q mailmerge_app` — passed.
- `node --check mailmerge_app/static/app.js` — passed.
- `python scripts/visual_review_e2e.py` — passed against a running local application; the review image is written to `artifacts/visual-review/senders.png`.
- Version consistency — package, runtime, pyproject and installer all **0.3.1**.
- Live loopback API smoke — `/api/health` returned `{"status":"ok","version":"0.3.1"}`.
- OAuth-specific regression coverage includes PKCE/login hints, canonical loopback redirect construction, single-use/bounded state sessions, no-store callback responses, reusable client setup, bearer-token validation, refresh-token rotation, invalid-grant handling, expected-account reconnect binding, least-privilege Sheets opt-in, non-secret health output and revocation.

## CI review evidence

The CI workflow uploads `MailDesk-Visual-Review-<commit>` for every push and pull request. The artifact contains the browser-generated Senders screenshot and service log, making the rendered OAuth account setup reviewable alongside the automated end-to-end assertions.
