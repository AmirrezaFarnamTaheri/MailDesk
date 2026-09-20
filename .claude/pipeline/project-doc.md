# Project Documentation
> Generated: 2026-09-20T13:57:44+03:30 | Mode: FULL

## Tech Stack
- Runtime: Python 3.11+ with a local Chromium-capable desktop environment
- Language: Python, browser-native JavaScript, HTML, and CSS
- Framework: FastAPI + Uvicorn loopback service; pywebview desktop shell
- Database: SQLite through the Python standard library
- Styling: project-local CSS with no frontend build step
- State Management: browser-local JavaScript state plus durable SQLite records

## Dependencies
- Core: FastAPI 0.116–0.x, Uvicorn 0.35–0.x, HTTPX 0.28–0.x, openpyxl 3.1–3.x, python-multipart 0.0.20–0.x, cryptography 45–46, pywebview 5.4–6.x
- Development/build: PyInstaller 6.x, httpx2 2.x
- Testing: pytest 8.x, Playwright 1.51–1.x

## Architecture Pattern
MailDesk is a modular local monolith. A pywebview shell hosts a browser-native frontend backed by one loopback-only FastAPI process and one SQLite database. External systems are adapters at the application boundary: local CSV/XLSX files, Google Sheets snapshots, Chromium Gmail sessions, and the Gmail API.

The server entry module currently combines HTTP composition, validation, and campaign worker orchestration. Domain-specific behavior remains in focused adapters and services. This is an established project constraint; new feature logic should prefer its owning module rather than further expanding `main.py`.

## Folder Structure
- `.github/workflows/` — cross-platform validation, Windows packaging, and visual-review CI
- `docs/` — architecture, security, OAuth integration, and user guidance
- `mailmerge_app/` — runtime package and application modules
- `mailmerge_app/static/` — single-page HTML/CSS/JavaScript frontend
- `packaging/` — PyInstaller and Inno Setup assets
- `scripts/` — local and CI screenshot/visual-review utilities
- `tests/` — API, domain, security, frontend-integrity, and regression tests

## Code Style Conventions
- Python uses snake_case functions, PascalCase classes, pathlib paths, explicit boundary validation, and type hints where they clarify public contracts.
- API handlers return plain JSON-compatible structures or raise `HTTPException` with user-safe details.
- Frontend elements are registered by ID in one `els` registry; integrity tests require every reference to exist and every HTML ID to be unique.
- Frontend code uses browser-native APIs and semantic state classes; no bundler or component framework is present.
- Tests are behavior-oriented `unittest.TestCase` methods collected by pytest.

## Modularity Practices
- Template parsing/rendering belongs in `template_engine.py`.
- CSV/XLSX detection and reading belongs in `sheet_reader.py`.
- Provider-neutral authorization-code, PKCE, token refresh/rotation, health, and revocation primitives belong in `oauth_client.py`.
- Google-specific Gmail and OAuth bindings belong in `gmail_client.py`; Google Sheets snapshot conversion belongs in `google_sheets.py`.
- Chromium discovery and Gmail `/u/N/` routing belong in `browser_profiles.py`.
- Persistence, encryption, migrations, backups, queue state, and audit records belong in `storage.py`.
- Desktop lifecycle and single-instance behavior belong in `desktop.py` and `instance.py`.

## Data Architecture
SQLite stores templates, reusable OAuth client configuration, per-account encrypted credentials, browser sender routes, imported-source metadata, attachments, campaign/message queue state, and history. Recipient data is normalized through the same import/preview/render pipeline whether it starts in the built-in worksheet, CSV/XLSX, or a Google Sheets snapshot. Secrets are encrypted before persistence; filesystem-key fallback is used only when the OS keyring boundary is unavailable.

## Cross-Cutting Concerns
- Authentication: MailDesk is an OAuth client, using authorization code + PKCE S256 with loopback callbacks, bounded one-time state, exact-origin popup handoff, reconnect identity binding, token rotation, and explicit revocation.
- Authorization surface: Gmail compose is the default Google scope; read-only Sheets access is opt-in.
- Error handling: external/provider errors are normalized and secrets are redacted before reaching the UI or logs.
- Validation: request models, worksheet schema limits, reserved/duplicate column checks, local-origin protection, attachment policy, send confirmation, and queue idempotency gates enforce boundaries.
- Accessibility: semantic controls, visible focus states, live regions, keyboard-accessible dialogs/tour, unique DOM IDs, and frontend integrity tests.

## Service Communication
- Browser/desktop UI to backend: local REST over `127.0.0.1`.
- Google: HTTPS OAuth token/userinfo, Gmail API, and optional Google Sheets API.
- Browser drafts: explicit local Chromium profile and Gmail account-slot routing.
- There is no remote MailDesk backend, message broker, or cloud database.

## Test Coverage
- Overall coverage: unavailable; the repository does not currently install a coverage plugin.
- Testing framework: pytest with standard-library unittest cases; Playwright for browser visual review.
- Current suite: 132 tests after the 0.4.0 worksheet/OAuth/visual-review integration.
- Key untested areas: OS-specific pywebview behavior, live Google authorization, and real Gmail delivery remain environment-dependent and require manual/provider integration checks.
- Test patterns: unit, FastAPI integration, repository/static integrity, security regressions, queue recovery, and browser-level visual smoke.

## Entry Points
- Desktop: `maildesk` / `mailmerge-desk` → `mailmerge_app.desktop:main`
- Local server: `maildesk-server` / `mailmerge-desk-server` → `mailmerge_app.main:run`
- Windows convenience launchers: `run.bat`, `run.ps1`
- CI: `.github/workflows/ci.yml`
- Windows packaging: `.github/workflows/build-windows.yml`

## Last Scanned
2026-09-20T13:57:44+03:30
