# Security and Safety Model

## Threats explicitly handled

- accidental use of the wrong Gmail API account;
- accidental use of the wrong `/u/N/` browser account;
- duplicate processing after retries/restarts;
- malformed recipient addresses;
- unresolved template placeholders;
- missing or oversized attachments;
- executable/script attachments;
- stale browser-session routing;
- a process crash during a real-send batch;
- database migration mistakes;
- accidental token disclosure through error strings.

## Sender verification

Gmail API credentials are refreshed and `/users/me/profile` is queried immediately before queue execution. The returned email must match the selected account.

Browser mode cannot securely introspect Gmail's internal account-slot assignment without browser automation/session access. Instead it opens the exact configured `/u/N/#inbox` and requires human confirmation that the visible account is the expected email. Verification expires after 30 minutes.

## Secrets

Google access/refresh tokens and client credentials are encrypted at rest:

- Windows: DPAPI tied to the current user.
- Non-Windows development: local Fernet key.

API responses never expose stored tokens or OAuth client secrets.

## Review and send gates

The rendering layer identifies invalid recipients, unresolved placeholders, missing attachments and other blocking errors. Real send additionally requires a final review checkbox and exact batch-bound confirmation text.

## Persistence and crash behavior

Queue items are stored before work starts. Every attempt is logged. A startup migration changes stale `Running` campaigns to `Paused`, requiring explicit resume. This avoids guessing whether a partially completed real-send batch should continue.

## Attachment policy

MailDesk blocks common executable/script extensions and enforces per-file and aggregate size limits. Browser compose mode refuses campaigns containing attachments because Gmail compose URLs cannot reliably attach files.

## Remaining trust boundaries

- Google and Gmail enforce their own API, abuse, quota and attachment policies.
- Browser-mode verification is explicitly human, not cryptographic.
- HTML email is authored by the local user; the preview is placed in a sandboxed iframe, but recipient mail clients remain responsible for their own HTML sanitization.
- The scheduling service is local; device availability is required.
