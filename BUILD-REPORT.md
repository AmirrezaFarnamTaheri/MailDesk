# MailDesk 0.2.0 — Implementation Report

## Completed backlog

| # | Area | Status | Delivered |
|---|---|---|---|
| 1 | Desktop productionization | Done | Native pywebview shell, single-instance guard, first-run UI, local state, app icon, migration backups, version/about, Windows packaging + optional signing |
| 2 | Template system | Done | Plain + HTML, signatures, snippets, placeholder browser, defaults, conditionals, attachments, CID inline images |
| 3 | Spreadsheet workflow | Done | XLSX/CSV drag-drop, header detection, mapping suggestions, filters, sorting, row selection, trim transform, campaign-only cell edits, duplicate warnings |
| 4 | Multi-account handling | Done | Gmail API accounts plus explicit browser/profile/Gmail `/u/N/` sender routes with expected-email verification |
| 5 | Send queue | Done | Durable message states, pause/resume/cancel/retry, throttling, queue inspection, restart-to-paused recovery |
| 6 | Safety | Done | Dry run, exact sender checks, per-message edits, fingerprints, attachment validation, executable blocking, batch caps, final send confirmation |
| 7 | Scheduling/history | Done | Local scheduling, campaign/row audit history, CSV export, campaign duplication into a new reviewed batch |
| 8 | GUI redesign | Done | Five-step workflow with sticky live preview and Accounts/Queue/History workspaces |
| 9 | Google Sheets | Done | Read-only OAuth scope, URL/ID import, local snapshot, worksheet selection, refresh-before-final-review path |
| 10 | Hardening/distribution | Done | Security headers/origin guard, HTML value escaping, secret-redacting errors, backups, 21 tests, Windows/Linux CI, dedicated final-EXE/installer workflow |

## Verification performed in this environment

- `python -m unittest discover -s tests -v` — **21 passed**.
- `python -m compileall -q mailmerge_app` — passed.
- `node --check mailmerge_app/static/app.js` — passed.
- UI reference integrity — **125 JavaScript element references, 0 missing IDs**.
- Version consistency — package, API, pyproject and installer all **0.2.0**.
- GitHub Actions workflow syntax — `.github/workflows/ci.yml` and `.github/workflows/build-windows.yml` parsed successfully.
- Dedicated Windows workflow — builds the EXE + installer, performs PE/MZ validation and a frozen-GUI marker-file startup smoke test on Windows, generates SHA-256 checksums, and uploads separate downloadable artifacts.
- Live localhost smoke:
  - `/api/health` → `{"status":"ok","version":"0.2.0"}`;
  - `/` → HTTP 200 and complete GUI;
  - security headers present;
  - simulated foreign Origin mutation → HTTP 403.

## Environment limitation

The Windows `.exe` / Inno Setup installer cannot be built natively in this Linux execution environment. The repository now includes a dedicated `.github/workflows/build-windows.yml` workflow that runs on GitHub-hosted Windows, executes `packaging/build-windows.ps1`, smoke-tests the frozen GUI `MailDesk.exe` through its headless marker-file mode, generates SHA-256 checksums, builds the installer, optionally signs both outputs, and uploads separate EXE and installer artifacts.

The requested hosted visual-design CLI was also attempted but its package installation timed out in this environment. The GUI was therefore implemented directly and verified structurally/functionally rather than claiming hosted image-to-code fidelity validation.
