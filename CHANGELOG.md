# Changelog

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
