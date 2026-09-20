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

Google access/refresh tokens, per-account OAuth clients, and the reusable Google Desktop OAuth client are encrypted at rest:

- Windows: DPAPI tied to the current user.
- Non-Windows development: local Fernet key.

API responses never expose stored tokens or OAuth client secrets. Account health endpoints return only non-secret metadata such as granted capability flags, refresh availability and expiry timestamps.


## OAuth lifecycle safety

- Authorization uses the OAuth 2.0 authorization-code flow with PKCE (S256) and a one-time random state value. The external browser returns to a `127.0.0.1` loopback callback derived from the actual local listener, not from an untrusted Host header.
- OAuth callback state is short-lived, single-use, memory-only and bounded; callback responses are marked `no-store`. Reconnect flows bind the callback to the expected Gmail address. A different Google identity is shown as an error and is not saved.
- Refresh-token rotation is supported; if Google returns a replacement refresh token, MailDesk persists the new value.
- `invalid_grant` and similar token failures become reconnect guidance rather than leaking upstream token payloads.
- Local **Disconnect** removes MailDesk's stored account only. Explicit revocation is separate because provider-side revocation is stronger and can invalidate the project's granted access.
- MailDesk does not fall back to username/password Gmail authentication or request the broad `https://mail.google.com/` scope merely to support SMTP/IMAP compatibility. New connections request only `gmail.compose` unless the user explicitly opts into read-only Google Sheets access.

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
