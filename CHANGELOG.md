# Changelog

## 0.4.1

- Replace typed live-send confirmation with a review dialog that identifies the Gmail account and message count.
- Bind browser drafts to the selected browser executable, user-data directory, and profile; show recovery guidance when a saved browser path is unavailable.

## 0.4.0

- added a built-in editable recipient worksheet with in-cell editing, row and column controls, rectangular clipboard paste, and in-place source updates;
- added one-click recipient-field insertion into the active subject or message editor;
- completed the OAuth 2.1-compatible desktop authorization flow with PKCE S256, bounded single-use state, exact-origin popup handoff, local browser session reuse, reconnect identity binding, and explicit revocation;
- added Playwright screenshot capture and CI visual-review artifacts for the real loopback application;
- added worksheet, OAuth lifecycle, queue-safety, accessibility-integrity, and remediation regression coverage;
- changed the project license to Apache License 2.0.

## 0.3.1

- Hardened the built-in Google OAuth 2.0 authorization-code flow: canonical loopback redirect construction, one-time callback state consumption, bounded authorization sessions, no-store callback responses, stricter bearer-token validation, and clearer provider errors.
- Google Sheets read-only permission is now opt-in for new connections; Gmail-only users request only the Gmail compose permission.
- Sender setup now identifies the flow explicitly as OAuth 2.0 + PKCE.

## 0.3.0

- integrated a reusable OAuth 2.0 client lifecycle module with PKCE, refresh-token rotation, safe provider errors and explicit revocation;
- added encrypted one-time Google Desktop OAuth client setup so additional Gmail accounts no longer require re-uploading the client JSON;
- added Gmail account health checks and account-bound reconnect flows that reject a callback for the wrong Google identity;
- exposed non-secret token health metadata without returning access tokens, refresh tokens or client secrets;
- retained the narrower Gmail API compose transport instead of embedding legacy password auth, OAuth 1.0, or the supplied IMAP/POP/SMTP proxy;
- documented the compatibility decisions for all supplied OAuth/Gmail reference projects;
- expanded OAuth, API and frontend regression coverage.

## 0.2.0

- redesigned five-stage campaign workflow;
- added explicit browser Gmail `/u/N/` sender routes and verification;
- added rich HTML templates, signatures, snippets, defaults and conditionals;
- added attachments and MIME Content-ID inline images;
- added Google Sheets read-only snapshot import/refresh;
- added mapping suggestions, row selection and campaign-only spreadsheet cell overrides;
- added persistent queue, pause/resume/cancel/retry, throttling and scheduling;
- added true dry-run campaigns and batch-bound real-send confirmation;
- added persistent campaign/history audit records and CSV export;
- added migration backups, secret/error redaction and configurable safety limits;
- added native desktop launcher and PyInstaller/Inno Setup packaging;
- added a dedicated GitHub Actions Windows build workflow with real frozen-GUI-EXE marker-file startup smoke testing, checksum generation, optional Authenticode signing, and separate EXE/installer artifacts;
- expanded regression suite for malformed files, RTL/Unicode, large sheets, queue recovery and Gmail slot routing.
