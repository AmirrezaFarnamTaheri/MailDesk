# Changelog

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
