# OAuth/Gmail Reference Integration

This change evaluated the four supplied reference projects and integrated only the pieces that fit MailDesk's current local-first Gmail architecture. The projects are **not vendored wholesale**: doing so would create duplicate auth stacks, broaden permissions, or reintroduce obsolete authentication methods.

## `email-oauth2-proxy`

Useful concepts adopted:

- explicit separation between provider metadata and OAuth lifecycle logic;
- PKCE-aware authorization-code handling;
- refresh-token lifecycle handling, including providers that rotate refresh tokens;
- explicit credential health/reconnect behavior;
- explicit provider-side token revocation as a separate action from local credential deletion.

Not embedded:

- the IMAP/POP/SMTP interception proxy;
- provider-specific password/device/service-account flows;
- Gmail SMTP via the broad `https://mail.google.com/` scope.

MailDesk already has a first-class Gmail API transport for drafts and sending. Running a local protocol proxy inside the desktop app would duplicate transport logic and require broader permissions for Gmail.

## `example-oauth2-server`

Useful concepts adopted:

- clear separation of authorization, token exchange, refresh, and protected-resource phases;
- explicit tests around authorization-code state and token lifecycle behavior.

Not embedded:

- an OAuth authorization server, grant database, password grant, implicit grant, or client-credentials grant.

MailDesk is an OAuth client. Becoming an authorization server would be the wrong trust boundary and add a second identity system that the product does not need.

## `python-oauth2`

This project explicitly implements **OAuth 1.0, not OAuth 2.0**. MailDesk therefore does not import or vendor its production code. Google account connection stays on OAuth 2.0 authorization code + PKCE.

## `gmail` (`gmail-master`)

The supplied project targets Python 2 and includes username/password IMAP login plus an early XOAUTH2 IMAP path. MailDesk does not copy that authentication model. It keeps the current Gmail REST API transport, MIME builder, narrow compose scope, explicit account-identity verification, and durable queue semantics.

## What changed in MailDesk

- New `mailmerge_app/oauth_client.py` reusable OAuth 2.0 lifecycle module.
- Encrypted `oauth_clients` storage for a reusable Google Desktop client.
- One-time Google OAuth setup followed by file-free additional account connections.
- Account **Check** and **Reconnect** flows.
- Reconnect callbacks are bound to the expected email account.
- Refresh-token rotation is persisted correctly.
- Safe `invalid_grant` handling with reconnect guidance.
- Explicit provider-side revocation endpoint, separate from local disconnect.
- Non-secret account health metadata in the API/UI.
- Regression tests for PKCE/login hints, refresh rotation, reconnect identity binding, reusable client setup, health checks, and revocation.

This keeps the useful OAuth engineering from the references while avoiding dead code, duplicate proxy stacks, legacy password auth, and unnecessary Gmail permission expansion.

## OAuth 2.1-compatible desktop authorization

MailDesk uses the installed/desktop-app **OAuth 2.0 authorization-code flow with PKCE (S256)**, following the OAuth 2.1 profile. It supports neither the implicit grant nor password-style grants. The browser is the external user agent and the authorization response returns to MailDesk over a loopback callback. The callback URI is built from the actual local listener and forced to the `127.0.0.1` loopback IP instead of trusting the HTTP `Host` header.

Authorization state is random, short-lived, single-use, and kept only in memory. Pending sessions are bounded so abandoned login attempts cannot grow memory without limit. OAuth callback responses are marked `no-store`. Token responses must contain a usable Bearer access token and positive expiry; refresh-token rotation continues to be preserved.

The desktop app opens a named, dedicated sign-in popup synchronously from the user gesture, then navigates it to Google. This lets Google reuse the account already signed in to the user's local browser while avoiding a pop-up blocker race. The completed loopback callback sends a result only to the exact known `127.0.0.1` opener origin; MailDesk refreshes connected accounts immediately and closes the popup. Closing the popup early produces a clear, non-destructive cancellation message.

New Gmail connections request only `gmail.compose` by default. `spreadsheets.readonly` is an explicit opt-in when Google Sheets is needed. Reconnecting an account never silently drops a Sheets grant it already has.
