from __future__ import annotations

import asyncio
import csv
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .browser_profiles import compose_url, discover_profiles, inbox_url, launch_compose, launch_url
from .gmail_client import (
    GMAIL_SCOPE,
    SHEETS_SCOPE,
    build_raw_message,
    create_draft,
    exchange_code,
    new_oauth_request,
    parse_client_secret,
    profile_email,
    refresh_token,
    send_message,
    spreadsheet_id_from_url,
    token_has_scope,
    token_is_valid,
)
from .google_sheets import snapshot_spreadsheet
from .instance import acquire_instance_lock
from .paths import attachments_dir, imports_dir
from .sheet_reader import SUPPORTED_EXTENSIONS, column_profiles, list_sheets, suggest_mappings, table
from .storage import Store
from .template_engine import batch_fingerprint, html_to_text, is_valid_email, message_fingerprint, render_text, split_addresses

APP_VERSION = "0.2.0"
STATIC_DIR = Path(__file__).with_name("static")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
BLOCKED_ATTACHMENT_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".jar"}
BROWSER_VERIFICATION_MINUTES = 30
IMPORT_TTL_HOURS = 24

store = Store()
imports: dict[str, dict[str, Any]] = {}
oauth_sessions: dict[str, dict[str, Any]] = {}
queue_tasks: dict[str, asyncio.Task] = {}
scheduler_task: asyncio.Task | None = None
campaign_run_lock: asyncio.Lock | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global scheduler_task, campaign_run_lock
    _cleanup_orphan_import_files()
    campaign_run_lock = asyncio.Lock()
    if scheduler_task is None or scheduler_task.done():
        scheduler_task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        tasks = list(queue_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        queue_tasks.clear()
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
            scheduler_task = None
        campaign_run_lock = None


app = FastAPI(title="MailDesk", version=APP_VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return Response("Local access only", status_code=403)
    origin = request.headers.get("origin")
    if origin and not (origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")):
        return Response("Cross-origin request blocked", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; frame-src 'self' data: blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


class TemplatePayload(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=200_000)
    body_html: str = Field(default="", max_length=400_000)
    signature_html: str = Field(default="", max_length=100_000)
    cc_template: str = Field(default="", max_length=4_000)
    bcc_template: str = Field(default="", max_length=4_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    tags: str = Field(default="", max_length=500)
    default_account: str = Field(default="", max_length=320)
    default_browser_sender_id: str = Field(default="", max_length=80)


class SnippetPayload(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=100_000)


class RenderRequest(BaseModel):
    import_id: str = Field(min_length=1, max_length=80)
    sheet: str = Field(min_length=1, max_length=255)
    header_row: int | None = Field(default=None, ge=1, le=1000)
    to_column: str = Field(max_length=255)
    name_column: str = Field(default="", max_length=255)
    cc_column: str = Field(default="", max_length=255)
    bcc_column: str = Field(default="", max_length=255)
    attachment_column: str = Field(default="", max_length=255)
    subject: str = Field(max_length=998)
    body: str = Field(max_length=200_000)
    body_html: str = Field(default="", max_length=400_000)
    signature_html: str = Field(default="", max_length=100_000)
    cc_template: str = Field(default="", max_length=4_000)
    bcc_template: str = Field(default="", max_length=4_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    filter_column: str = Field(default="", max_length=255)
    filter_operator: Literal["equals", "contains", "not_empty"] = "equals"
    filter_value: str = Field(default="", max_length=20_000)
    sort_column: str = Field(default="", max_length=255)
    sort_direction: Literal["asc", "desc"] = "asc"
    selected_rows: list[str] = Field(default_factory=list, max_length=100_000)
    row_overrides: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100_000)
    limit: int = Field(default=0, ge=0, le=100_000)
    trim_values: bool = True


class MessagePayload(BaseModel):
    row_number: str = Field(max_length=40)
    display_name: str = Field(default="", max_length=1_000)
    to: str = Field(max_length=4_000)
    cc: str = Field(default="", max_length=4_000)
    bcc: str = Field(default="", max_length=4_000)
    subject: str = Field(max_length=998)
    body: str = Field(max_length=200_000)
    body_html: str = Field(default="", max_length=400_000)
    attachments: list[str] = Field(default_factory=list, max_length=20)
    errors: list[str] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class BatchHashRequest(BaseModel):
    messages: list[MessagePayload] = Field(max_length=10_000)


class BrowserSenderPayload(BaseModel):
    id: str = Field(default="", max_length=80)
    label: str = Field(min_length=1, max_length=120)
    browser_id: str = Field(min_length=1, max_length=40)
    profile_dir: str = Field(min_length=1, max_length=120)
    gmail_slot: int = Field(ge=0, le=99)
    expected_email: str = Field(min_length=3, max_length=320)


class GoogleSheetImportRequest(BaseModel):
    account: str = Field(min_length=3, max_length=320)
    spreadsheet: str = Field(min_length=1, max_length=2_048)


class CampaignRequest(BaseModel):
    name: str = Field(default="", max_length=160)
    source_name: str = Field(default="", max_length=260)
    mode: Literal["dry_run", "browser", "draft", "send"]
    account: str = Field(default="", max_length=320)
    browser_sender_id: str = Field(default="", max_length=80)
    batch_id: str = Field(min_length=12, max_length=128)
    messages: list[MessagePayload] = Field(max_length=10_000)
    skip_duplicates: bool = True
    throttle_ms: int = Field(default=750, ge=0, le=60_000)
    scheduled_at: str = Field(default="", max_length=80)
    reviewed: bool = False
    confirm_text: str = Field(default="", max_length=200)


class SettingsPayload(BaseModel):
    max_batch_size: int = Field(default=500, ge=1, le=10_000)
    default_throttle_ms: int = Field(default=750, ge=0, le=60_000)


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/about")
async def about() -> dict[str, Any]:
    return {
        "name": "MailDesk",
        "version": APP_VERSION,
        "local_first": True,
        "gmail_scope": GMAIL_SCOPE,
        "sheets_scope": SHEETS_SCOPE,
        "browser_verification_minutes": BROWSER_VERIFICATION_MINUTES,
    }


# ---------- templates / snippets ----------
@app.get("/api/templates")
async def templates_list() -> list[dict[str, Any]]:
    return store.list_templates()


@app.put("/api/templates/{template_id}")
async def templates_save(template_id: str, payload: TemplatePayload) -> dict[str, Any]:
    if payload.id != template_id:
        raise HTTPException(400, "Template id does not match the route.")
    _validate_attachment_ids(payload.attachment_ids)
    return store.save_template(payload.model_dump())


@app.delete("/api/templates/{template_id}")
async def templates_delete(template_id: str) -> dict[str, bool]:
    store.delete_template(template_id)
    return {"deleted": True}


@app.get("/api/snippets")
async def snippets_list() -> list[dict[str, str]]:
    return store.list_snippets()


@app.put("/api/snippets/{snippet_id}")
async def snippets_save(snippet_id: str, payload: SnippetPayload) -> dict[str, str]:
    if payload.id != snippet_id:
        raise HTTPException(400, "Snippet id does not match the route.")
    return store.save_snippet(payload.model_dump())


@app.delete("/api/snippets/{snippet_id}")
async def snippets_delete(snippet_id: str) -> dict[str, bool]:
    store.delete_snippet(snippet_id)
    return {"deleted": True}


# ---------- attachments ----------
@app.get("/api/attachments")
async def attachments_list() -> list[dict[str, Any]]:
    return store.list_attachments()


@app.post("/api/attachments")
async def attachments_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "attachment").name
    if Path(filename).suffix.lower() in BLOCKED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(400, "Executable/script attachments are blocked by MailDesk.")
    attachment_id = uuid.uuid4().hex
    stored_name = f"{attachment_id}{Path(filename).suffix.lower()}"
    path = attachments_dir() / stored_name
    size = 0
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ATTACHMENT_BYTES:
                output.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, "Attachment is larger than 20 MB.")
            output.write(chunk)
    return store.save_attachment({
        "id": attachment_id,
        "name": filename,
        "stored_name": stored_name,
        "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
        "size": size,
    })


@app.get("/api/attachments/{attachment_id}/content")
async def attachment_content(attachment_id: str) -> FileResponse:
    item = store.get_attachment(attachment_id)
    if not item:
        raise HTTPException(404, "Attachment not found.")
    path = attachments_dir() / item["stored_name"]
    if not path.exists():
        raise HTTPException(404, "Attachment file is missing.")
    return FileResponse(path, media_type=item.get("mime_type") or "application/octet-stream")


@app.delete("/api/attachments/{attachment_id}")
async def attachments_delete(attachment_id: str) -> dict[str, bool]:
    if store.attachment_in_use(attachment_id):
        raise HTTPException(409, "This attachment is used by a saved template or active campaign. Remove that reference first.")
    item = store.delete_attachment(attachment_id)
    if item:
        (attachments_dir() / item["stored_name"]).unlink(missing_ok=True)
    return {"deleted": bool(item)}


# ---------- spreadsheet sources ----------
@app.post("/api/imports")
async def import_sheet(file: UploadFile = File(...)) -> dict[str, Any]:
    _prune_imports()
    filename = Path(file.filename or "spreadsheet").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, "Use an .xlsx, .xlsm, or .csv file.")
    import_id = uuid.uuid4().hex
    path = imports_dir() / f"{import_id}{suffix}"
    size = 0
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                output.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, "Spreadsheet is larger than 25 MB.")
            output.write(chunk)
    try:
        sheets = list_sheets(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read spreadsheet: {_safe_error(exc)}") from exc
    meta = {
        "import_id": import_id, "filename": filename, "size": size, "sheets": sheets,
        "source_type": "file", "path": path, "snapshot_at": _utc_now(),
    }
    imports[import_id] = meta
    return _public_import(meta)


@app.post("/api/imports/google-sheet")
async def import_google_sheet(payload: GoogleSheetImportRequest) -> dict[str, Any]:
    _prune_imports()
    try:
        spreadsheet_id = spreadsheet_id_from_url(payload.spreadsheet)
        token, _ = await _verified_google_account(payload.account, require_scope=SHEETS_SCOPE)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(400, _safe_error(exc)) from exc
    import_id = uuid.uuid4().hex
    path = imports_dir() / f"{import_id}.xlsx"
    try:
        snapshot = await snapshot_spreadsheet(token, spreadsheet_id, path)
    except httpx.HTTPError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(502, f"Could not read Google Sheet: {_safe_error(exc)}") from exc
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    meta = {
        "import_id": import_id,
        "filename": snapshot["title"],
        "size": path.stat().st_size,
        "sheets": snapshot["sheets"],
        "source_type": "google_sheet",
        "path": path,
        "snapshot_at": _utc_now(),
        "google_account": payload.account,
        "spreadsheet_id": spreadsheet_id,
        "total_cells": snapshot["total_cells"],
    }
    imports[import_id] = meta
    return _public_import(meta)


@app.post("/api/imports/{import_id}/refresh")
async def refresh_import(import_id: str) -> dict[str, Any]:
    meta = _import_meta(import_id)
    if meta.get("source_type") != "google_sheet":
        raise HTTPException(400, "Only live Google Sheet imports can be refreshed.")
    token, _ = await _verified_google_account(str(meta["google_account"]), require_scope=SHEETS_SCOPE)
    try:
        snapshot = await snapshot_spreadsheet(token, str(meta["spreadsheet_id"]), Path(meta["path"]))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not refresh Google Sheet: {_safe_error(exc)}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta.update({"filename": snapshot["title"], "sheets": snapshot["sheets"], "size": Path(meta["path"]).stat().st_size, "snapshot_at": _utc_now(), "total_cells": snapshot["total_cells"]})
    return _public_import(meta)


@app.get("/api/imports/{import_id}")
async def import_info(import_id: str) -> dict[str, Any]:
    return _public_import(_import_meta(import_id))


@app.get("/api/imports/{import_id}/preview")
async def import_preview(import_id: str, sheet: str = Query(...), header_row: int | None = Query(default=None, ge=1, le=1000)) -> dict[str, Any]:
    path = _import_path(import_id)
    try:
        headers, rows, detected = table(path, sheet, header_row)
    except Exception as exc:
        raise HTTPException(400, _safe_error(exc)) from exc
    return {
        "headers": headers,
        "header_row": detected,
        "total_rows": len(rows),
        "rows": rows[:100],
        "row_numbers": [row.get("_row", "") for row in rows],
        "column_profiles": column_profiles(headers, rows),
        "suggestions": suggest_mappings(headers, rows),
        "source": _public_import(_import_meta(import_id)),
    }


@app.post("/api/render")
async def render_messages(payload: RenderRequest) -> dict[str, Any]:
    path = _import_path(payload.import_id)
    try:
        headers, rows, detected = table(path, payload.sheet, payload.header_row)
    except Exception as exc:
        raise HTTPException(400, _safe_error(exc)) from exc
    _validate_mapping_columns(payload, headers)

    if payload.selected_rows:
        selected = set(payload.selected_rows)
        rows = [row for row in rows if row.get("_row") in selected]
    if payload.row_overrides:
        for row in rows:
            override = payload.row_overrides.get(row.get("_row", ""), {})
            for column, value in override.items():
                if column in headers:
                    row[column] = value
    if payload.filter_column:
        rows = [row for row in rows if _filter_row(row.get(payload.filter_column, ""), payload.filter_operator, payload.filter_value)]
    if payload.sort_column:
        rows = sorted(
            rows,
            key=lambda row: str(row.get(payload.sort_column, "")).casefold(),
            reverse=payload.sort_direction == "desc",
        )
    if payload.limit:
        rows = rows[: payload.limit]

    attachment_by_name = {item["name"].casefold(): item["id"] for item in reversed(store.list_attachments())}
    messages = [_render_row(payload, row, attachment_by_name) for row in rows]
    _mark_duplicate_recipients(messages)
    invalid = sum(bool(message["errors"]) for message in messages)
    warnings = sum(bool(message["warnings"]) for message in messages)
    batch_id = batch_fingerprint(messages)
    return {
        "headers": headers,
        "header_row": detected,
        "total": len(messages),
        "valid": len(messages) - invalid,
        "invalid": invalid,
        "with_warnings": warnings,
        "batch_id": batch_id,
        "messages": messages,
        "source": _public_import(_import_meta(payload.import_id)),
    }


@app.post("/api/batch-id")
async def batch_id(payload: BatchHashRequest) -> dict[str, str]:
    return {"batch_id": batch_fingerprint([message.model_dump() for message in payload.messages])}


# ---------- browser profiles and Gmail account slots ----------
@app.get("/api/browser-profiles")
async def browser_profiles() -> list[dict[str, object]]:
    return discover_profiles()


@app.get("/api/browser-senders")
async def browser_senders_list() -> list[dict[str, Any]]:
    return store.list_browser_senders()


@app.put("/api/browser-senders/{sender_id}")
async def browser_sender_save(sender_id: str, payload: BrowserSenderPayload) -> dict[str, Any]:
    if payload.id and payload.id != sender_id:
        raise HTTPException(400, "Browser sender id does not match the route.")
    if not is_valid_email(payload.expected_email):
        raise HTTPException(400, "Expected sender email is invalid.")
    profiles = discover_profiles()
    selected = next((p for p in profiles if p["browser_id"] == payload.browser_id and p["profile_dir"] == payload.profile_dir), None)
    if selected is None:
        raise HTTPException(400, "The selected browser profile is not currently available.")
    existing = store.get_browser_sender(sender_id)
    item = payload.model_dump()
    item["id"] = sender_id
    if existing and any(str(existing.get(key)) != str(item.get(key)) for key in ("browser_id", "profile_dir", "gmail_slot", "expected_email")):
        item["verified_at"] = ""
    return store.save_browser_sender(item)


@app.delete("/api/browser-senders/{sender_id}")
async def browser_sender_delete(sender_id: str) -> dict[str, bool]:
    if store.browser_sender_in_use(sender_id):
        raise HTTPException(409, "This browser sender route is used by an active campaign. Cancel or finish that campaign first.")
    store.delete_browser_sender(sender_id)
    return {"deleted": True}


@app.post("/api/browser-senders/{sender_id}/verify/open")
async def browser_sender_verify_open(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(404, "Browser sender route not found.")
    profile = _profile_for_sender(sender)
    launch_url(profile, inbox_url(int(sender["gmail_slot"])))
    return {"opened": True, "expected_email": sender["expected_email"], "gmail_slot": sender["gmail_slot"]}


@app.post("/api/browser-senders/{sender_id}/verify/confirm")
async def browser_sender_verify_confirm(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(404, "Browser sender route not found.")
    store.mark_browser_sender_verified(sender_id)
    return store.get_browser_sender(sender_id) or {}


# ---------- Google accounts ----------
@app.get("/api/accounts")
async def accounts_list() -> list[dict[str, Any]]:
    output = []
    for item in store.list_accounts():
        try:
            account = store.get_account(item["email"])
            scopes = str(account[0].get("scope") or "") if account else ""
            output.append({**item, "gmail": GMAIL_SCOPE in scopes, "sheets": SHEETS_SCOPE in scopes, "credential_error": ""})
        except Exception:
            output.append({**item, "gmail": False, "sheets": False, "credential_error": "Stored credentials could not be read. Disconnect and reconnect this account."})
    return output


@app.post("/api/accounts/google/start")
async def google_start(request: Request, client_secret: UploadFile = File(...), include_sheets: bool = Form(True)) -> dict[str, str]:
    raw = await client_secret.read(2 * 1024 * 1024)
    if not raw:
        raise HTTPException(400, "OAuth client JSON is empty.")
    try:
        client = parse_client_secret(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    redirect_uri = str(request.base_url).rstrip("/") + "/oauth/google/callback"
    scopes = [GMAIL_SCOPE] + ([SHEETS_SCOPE] if include_sheets else [])
    auth_url, session = new_oauth_request(client, redirect_uri, scopes=scopes)
    oauth_sessions[session["state"]] = {**session, "client": client, "created": time.time()}
    _prune_oauth_sessions()
    return {"auth_url": auth_url}


@app.get("/oauth/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    if error:
        return _oauth_page(False, f"Google authorization failed: {error}")
    session = oauth_sessions.pop(state, None)
    if not session or time.time() - session.get("created", 0) > 600:
        return _oauth_page(False, "Authorization session expired. Return to MailDesk and connect again.")
    if not code:
        return _oauth_page(False, "Google did not return an authorization code.")
    try:
        token = await exchange_code(session["client"], code, session["verifier"], session["redirect_uri"])
        token["scope"] = token.get("scope") or session.get("requested_scopes", "")
        email_address = await profile_email(token)
        store.save_account(email_address, token, session["client"])
        return _oauth_page(True, f"Connected {email_address}. You can close this tab.")
    except Exception as exc:
        return _oauth_page(False, f"Could not connect Google: {_safe_error(exc)}")


@app.delete("/api/accounts/{email}")
async def accounts_delete(email: str) -> dict[str, bool]:
    if store.account_in_use(email):
        raise HTTPException(409, "This Google account is used by an active campaign. Cancel or finish that campaign first.")
    store.delete_account(email)
    return {"deleted": True}


# ---------- campaign queue / scheduling ----------
@app.post("/api/campaigns")
async def campaign_create(payload: CampaignRequest) -> dict[str, Any]:
    _ensure_messages_safe(payload.messages)
    max_batch = int(store.get_setting("max_batch_size", "500") or "500")
    if len(payload.messages) > max_batch:
        raise HTTPException(400, f"Batch has {len(payload.messages)} messages; current safety limit is {max_batch}.")
    expected_batch = batch_fingerprint([m.model_dump() for m in payload.messages])
    if payload.batch_id != expected_batch:
        raise HTTPException(409, "Rendered batch changed. Review the latest batch before processing.")

    if payload.mode == "send":
        expected = f"SEND {len(payload.messages)} {payload.batch_id[:8].upper()}"
        if not payload.reviewed or payload.confirm_text.strip() != expected:
            raise HTTPException(400, f"Sending requires review and typing exactly: {expected}")
        if not payload.account:
            raise HTTPException(400, "Select a connected Gmail account.")
    elif payload.mode == "draft" and not payload.account:
        raise HTTPException(400, "Select a connected Gmail account.")
    elif payload.mode == "browser":
        sender = _require_fresh_browser_sender(payload.browser_sender_id)
        if any(message.attachments for message in payload.messages):
            raise HTTPException(400, "Browser compose URLs cannot attach files. Use Gmail drafts/send or remove attachments.")
        payload.account = str(sender["expected_email"])

    scheduled_at = _normalize_schedule(payload.scheduled_at)
    status = "Scheduled" if scheduled_at else "Queued"
    account_label = payload.account
    if payload.mode == "browser":
        sender = store.get_browser_sender(payload.browser_sender_id)
        account_label = sender["expected_email"] if sender else ""
    messages = []
    for message in payload.messages:
        item = message.model_dump()
        item["fingerprint"] = message_fingerprint(
            payload.mode, account_label, message.to, message.cc, message.bcc, message.subject, message.body,
            message.body_html, message.attachments,
        )
        messages.append(item)
    campaign = store.create_campaign(
        {
            "name": payload.name,
            "source_name": payload.source_name,
            "mode": payload.mode,
            "account": payload.account,
            "browser_sender_id": payload.browser_sender_id,
            "batch_id": payload.batch_id,
            "status": status,
            "scheduled_at": scheduled_at,
            "throttle_ms": payload.throttle_ms,
            "skip_duplicates": payload.skip_duplicates,
        },
        messages,
    )
    if status == "Queued":
        _start_campaign_task(campaign["id"])
    return campaign


@app.get("/api/campaigns")
async def campaigns_list(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return store.list_campaigns(limit)


@app.get("/api/campaigns/{campaign_id}")
async def campaign_get(campaign_id: str) -> dict[str, Any]:
    campaign = store.get_campaign(campaign_id, include_items=True)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    return campaign


@app.post("/api/campaigns/{campaign_id}/pause")
async def campaign_pause(campaign_id: str) -> dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] in {"Completed", "CompletedWithErrors", "Cancelled"}:
        raise HTTPException(400, f"Cannot pause a {campaign['status'].lower()} campaign.")
    store.set_campaign_status(campaign_id, "Paused")
    return store.get_campaign(campaign_id, include_items=True) or {}


@app.post("/api/campaigns/{campaign_id}/resume")
async def campaign_resume(campaign_id: str) -> dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] in {"Completed", "CompletedWithErrors", "Cancelled"}:
        raise HTTPException(400, f"Cannot resume a {campaign['status'].lower()} campaign.")
    if store.queue_items(campaign_id, statuses=("NeedsReview",)):
        raise HTTPException(409, "Resolve the uncertain Gmail outcome before resuming this campaign.")
    if not store.queue_items(campaign_id):
        raise HTTPException(400, "This campaign has no pending items to resume.")
    if campaign["mode"] == "browser":
        _require_fresh_browser_sender(campaign["browser_sender_id"])
    store.set_campaign_status(campaign_id, "Queued")
    _start_campaign_task(campaign_id)
    return store.get_campaign(campaign_id, include_items=True) or {}


@app.post("/api/campaigns/{campaign_id}/cancel")
async def campaign_cancel(campaign_id: str) -> dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] in {"Completed", "CompletedWithErrors"}:
        raise HTTPException(400, f"Cannot cancel a {campaign['status'].lower()} campaign.")
    if campaign["status"] != "Cancelled":
        store.set_campaign_status(campaign_id, "Cancelled")
    return store.get_campaign(campaign_id, include_items=True) or {}


@app.post("/api/campaigns/{campaign_id}/retry-failed")
async def campaign_retry(campaign_id: str) -> dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] == "Cancelled":
        raise HTTPException(400, "Cannot retry a cancelled campaign.")
    if store.queue_items(campaign_id, statuses=("NeedsReview",)):
        raise HTTPException(409, "Resolve the uncertain Gmail outcome before retrying failed items.")
    if campaign["mode"] == "browser":
        _require_fresh_browser_sender(campaign["browser_sender_id"])
    retried = store.retry_failed(campaign_id)
    if retried <= 0:
        raise HTTPException(400, "This campaign has no failed items to retry.")
    store.set_campaign_status(campaign_id, "Queued")
    _start_campaign_task(campaign_id)
    return store.get_campaign(campaign_id, include_items=True) or {}


@app.post("/api/campaigns/{campaign_id}/items/{item_id}/resolve-sent")
async def campaign_resolve_uncertain_sent(campaign_id: str, item_id: int) -> dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    item = store.get_queue_item(campaign_id, item_id)
    if not item:
        raise HTTPException(404, "Campaign item not found.")
    if item["status"] != "NeedsReview":
        raise HTTPException(400, "Only an item awaiting outcome review can be resolved.")
    if campaign["mode"] not in {"send", "draft"}:
        raise HTTPException(400, "Outcome review is only used for Gmail API sends/drafts.")
    remote_id = "ConfirmedByUser"
    store.update_item(item_id, status="Success", remote_id=remote_id, error="")
    store.log_operation({
        **_operation_from_item(campaign, item, campaign.get("account", "")),
        "remote_id": remote_id,
        "result": "Success",
        "error": "User confirmed the Gmail operation completed after an uncertain API response.",
    })
    store.refresh_campaign_counts(campaign_id)
    store.set_campaign_status(campaign_id, "Paused", error="Uncertain outcome resolved as completed. Review remaining work before resuming.")
    return store.get_campaign(campaign_id, include_items=True) or {}


@app.post("/api/campaigns/{campaign_id}/items/{item_id}/resolve-not-sent")
async def campaign_resolve_uncertain_not_sent(campaign_id: str, item_id: int) -> dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    item = store.get_queue_item(campaign_id, item_id)
    if not item:
        raise HTTPException(404, "Campaign item not found.")
    if item["status"] != "NeedsReview":
        raise HTTPException(400, "Only an item awaiting outcome review can be resolved.")
    if campaign["mode"] not in {"send", "draft"}:
        raise HTTPException(400, "Outcome review is only used for Gmail API sends/drafts.")
    error = "User confirmed the Gmail operation did not complete after an uncertain API response."
    store.update_item(item_id, status="Failed", remote_id="", error=error)
    store.log_operation({**_operation_from_item(campaign, item, campaign.get("account", "")), "result": "Failed", "error": error})
    store.refresh_campaign_counts(campaign_id)
    store.set_campaign_status(campaign_id, "Paused", error="Uncertain outcome resolved as not completed. Retry the failed item only if appropriate.")
    return store.get_campaign(campaign_id, include_items=True) or {}


@app.get("/api/history")
async def history(limit: int = Query(default=300, ge=1, le=2000)) -> list[dict[str, Any]]:
    return store.history(limit)


@app.get("/api/history.csv")
async def history_csv(limit: int = Query(default=2000, ge=1, le=20_000)) -> StreamingResponse:
    rows = store.history(limit)
    stream = io.StringIO()
    fields = ["timestamp_utc", "campaign_id", "mode", "account", "row_number", "recipient", "subject", "remote_id", "result", "error"]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key, "")) for key in fields})
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=maildesk-history.csv"})


# ---------- settings / backup ----------
@app.get("/api/settings")
async def settings_get() -> dict[str, int]:
    return {
        "max_batch_size": int(store.get_setting("max_batch_size", "500") or "500"),
        "default_throttle_ms": int(store.get_setting("default_throttle_ms", "750") or "750"),
    }


@app.put("/api/settings")
async def settings_save(payload: SettingsPayload) -> dict[str, int]:
    store.set_setting("max_batch_size", str(payload.max_batch_size))
    store.set_setting("default_throttle_ms", str(payload.default_throttle_ms))
    return payload.model_dump()


@app.post("/api/backup")
async def backup_database() -> dict[str, str]:
    path = store.backup()
    return {"backup": str(path)}


# ---------- rendering helpers ----------
def _render_row(payload: RenderRequest, row: dict[str, str], attachment_by_name: dict[str, str]) -> dict[str, Any]:
    working = {key: (value.strip() if payload.trim_values and isinstance(value, str) else value) for key, value in row.items()}
    row_number = int(row.get("_row", "0") or 0)
    subject = render_text(payload.subject, working, row_number)
    body = render_text(payload.body, working, row_number)
    html_result = render_text(payload.body_html, working, row_number, escape_values=True)
    signature_result = render_text(payload.signature_html, working, row_number, escape_values=True)
    cc_template = render_text(payload.cc_template, working, row_number)
    bcc_template = render_text(payload.bcc_template, working, row_number)

    to = str(working.get(payload.to_column, "")).strip()
    cc_column = str(working.get(payload.cc_column, "")).strip() if payload.cc_column else ""
    bcc_column = str(working.get(payload.bcc_column, "")).strip() if payload.bcc_column else ""
    cc_text = _merge_addresses(cc_column, cc_template.text)
    bcc_text = _merge_addresses(bcc_column, bcc_template.text)

    body_html = html_result.text.strip()
    if signature_result.text.strip():
        body_html = (body_html + "<br><br>" + signature_result.text.strip()).strip()
    if body_html and not body.text.strip():
        body = render_text(html_to_text(body_html), working, row_number)

    errors: list[str] = []
    warnings: list[str] = []
    unresolved = sorted(set(subject.unresolved + body.unresolved + html_result.unresolved + signature_result.unresolved + cc_template.unresolved + bcc_template.unresolved))
    if unresolved:
        errors.append("Unknown placeholder(s): " + ", ".join(unresolved))
    blank_values = sorted(set(subject.blank_values + body.blank_values + html_result.blank_values + signature_result.blank_values + cc_template.blank_values + bcc_template.blank_values))
    if blank_values:
        warnings.append("Blank value(s): " + ", ".join(blank_values))

    to_addresses = split_addresses(to)
    invalid_to = [address for address in to_addresses if not is_valid_email(address)]
    invalid_cc = [address for address in split_addresses(cc_text) if not is_valid_email(address)]
    invalid_bcc = [address for address in split_addresses(bcc_text) if not is_valid_email(address)]
    if not to_addresses:
        errors.append("Recipient is blank.")
    if invalid_to:
        errors.append("Invalid recipient: " + ", ".join(invalid_to))
    if invalid_cc:
        errors.append("Invalid Cc: " + ", ".join(invalid_cc))
    if invalid_bcc:
        errors.append("Invalid Bcc: " + ", ".join(invalid_bcc))
    if not subject.text.strip():
        warnings.append("Subject is blank.")
    if not body.text.strip() and not body_html:
        warnings.append("Body is blank.")

    attachment_ids = list(dict.fromkeys(payload.attachment_ids))
    if payload.attachment_column:
        raw_attachments = str(working.get(payload.attachment_column, ""))
        for value in [part.strip() for part in re.split(r"[;,\n]+", raw_attachments) if part.strip()]:
            if store.get_attachment(value):
                attachment_ids.append(value)
            elif value.casefold() in attachment_by_name:
                attachment_ids.append(attachment_by_name[value.casefold()])
            else:
                errors.append(f"Attachment not found in app library: {value}")
    attachment_ids = list(dict.fromkeys(attachment_ids))
    try:
        _validate_attachment_ids(attachment_ids)
    except HTTPException as exc:
        errors.append(str(exc.detail))

    return {
        "row_number": row.get("_row", ""),
        "display_name": str(working.get(payload.name_column, "")).strip() if payload.name_column else "",
        "to": ", ".join(to_addresses),
        "cc": cc_text,
        "bcc": bcc_text,
        "subject": subject.text,
        "body": body.text,
        "body_html": body_html,
        "attachments": attachment_ids,
        "errors": errors,
        "warnings": warnings,
        "source": working,
    }


def _mark_duplicate_recipients(messages: list[dict[str, Any]]) -> None:
    seen: dict[str, str] = {}
    for message in messages:
        key = message["to"].casefold().strip()
        if not key:
            continue
        if key in seen:
            message["warnings"].append(f"Recipient also appears in row {seen[key]}.")
        else:
            seen[key] = message["row_number"]


def _ensure_messages_safe(messages: list[MessagePayload]) -> None:
    if not messages:
        raise HTTPException(400, "There are no messages to process.")
    unsafe = [message.row_number for message in messages if message.errors]
    if unsafe:
        raise HTTPException(400, "Fix validation errors before processing rows: " + ", ".join(unsafe[:12]))
    for message in messages:
        recipients = split_addresses(message.to)
        if not recipients:
            raise HTTPException(400, f"Recipient is blank in row {message.row_number}.")
        for address in recipients + split_addresses(message.cc) + split_addresses(message.bcc):
            if not is_valid_email(address):
                raise HTTPException(400, f"Invalid email address in row {message.row_number}: {address}")
        _validate_attachment_ids(message.attachments)


def _validate_attachment_ids(ids: list[str]) -> None:
    total = 0
    missing = []
    for attachment_id in ids:
        item = store.get_attachment(attachment_id)
        if not item or not (attachments_dir() / item["stored_name"]).exists():
            missing.append(attachment_id)
        else:
            total += int(item["size"])
    if missing:
        raise HTTPException(400, "Missing attachment(s): " + ", ".join(missing[:8]))
    if total > 24 * 1024 * 1024:
        raise HTTPException(400, "Selected attachments exceed the 24 MB pre-encoding safety limit.")


def _attachment_payloads(
    ids: list[str], body_html: str = ""
) -> tuple[list[tuple[str, bytes, str | None]], list[tuple[str, str, bytes, str | None]]]:
    regular: list[tuple[str, bytes, str | None]] = []
    inline: list[tuple[str, str, bytes, str | None]] = []
    for attachment_id in ids:
        item = store.get_attachment(attachment_id)
        if not item:
            raise RuntimeError(f"Attachment disappeared: {attachment_id}")
        path = attachments_dir() / item["stored_name"]
        if not path.is_file():
            raise RuntimeError(f"Attachment file disappeared: {item['name']}")
        payload = path.read_bytes()
        mime_type = item.get("mime_type") or mimetypes.guess_type(item["name"])[0]
        if f"cid:{attachment_id}" in (body_html or "") and str(mime_type or "").startswith("image/"):
            inline.append((attachment_id, item["name"], payload, mime_type))
        else:
            regular.append((item["name"], payload, mime_type))
    return regular, inline


# ---------- queue worker ----------
async def _scheduler_loop() -> None:
    try:
        while True:
            for campaign_id in store.due_campaigns():
                store.set_campaign_status(campaign_id, "Queued")
                _start_campaign_task(campaign_id)
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        return


def _start_campaign_task(campaign_id: str) -> None:
    task = queue_tasks.get(campaign_id)
    if task and not task.done():
        return
    task = asyncio.create_task(_run_campaign(campaign_id))
    queue_tasks[campaign_id] = task

    def discard(finished: asyncio.Task) -> None:
        if queue_tasks.get(campaign_id) is finished:
            queue_tasks.pop(campaign_id, None)

    task.add_done_callback(discard)


async def _run_campaign(campaign_id: str) -> None:
    global campaign_run_lock
    if campaign_run_lock is None:
        campaign_run_lock = asyncio.Lock()
    async with campaign_run_lock:
        await _run_campaign_locked(campaign_id)


async def _run_campaign_locked(campaign_id: str) -> None:
    campaign = store.get_campaign(campaign_id)
    # A task can wait behind another campaign long enough for the user to pause or
    # cancel it. Re-check the persisted state only after acquiring the global lock.
    if not campaign or campaign["status"] not in {"Queued", "Running"}:
        return
    mode = campaign["mode"]
    account_label = campaign.get("account", "")
    browser_profile: dict[str, Any] | None = None
    gmail_token: dict[str, Any] | None = None
    try:
        if mode == "browser":
            sender = _require_fresh_browser_sender(campaign["browser_sender_id"])
            browser_profile = _profile_for_sender(sender)
            account_label = sender["expected_email"]
        elif mode in {"draft", "send"}:
            gmail_token, actual = await _verified_google_account(campaign["account"], require_scope=GMAIL_SCOPE)
            account_label = actual
        store.set_campaign_status(campaign_id, "Running")

        items = store.queue_items(campaign_id)
        for item_index, item in enumerate(items):
            current = store.get_campaign(campaign_id)
            if not current or current["status"] in {"Paused", "Cancelled"}:
                return
            if int(current.get("skip_duplicates", 1)) and store.fingerprint_succeeded(item["fingerprint"]):
                store.update_item(item["id"], status="Skipped", error="Already processed successfully.")
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Skipped", "error": "Already processed successfully."})
                store.refresh_campaign_counts(campaign_id)
                continue

            if mode in {"draft", "send"} and not token_is_valid(gmail_token or {}, margin_seconds=120):
                gmail_token, actual = await _verified_google_account(current["account"], require_scope=GMAIL_SCOPE)
                account_label = actual

            try:
                remote_id = ""
                if mode == "dry_run":
                    remote_id = "DryRunOnly"
                elif mode == "browser":
                    try:
                        sender = _require_fresh_browser_sender(current["browser_sender_id"])
                        url = compose_url(item["recipient"], item["subject"], item["body"], item["cc"], item["bcc"], int(sender["gmail_slot"]))
                        launch_compose(browser_profile or _profile_for_sender(sender), url)
                    except Exception as exc:
                        store.set_campaign_status(campaign_id, "Paused", error=_safe_error(exc))
                        return
                    remote_id = f"BrowserCompose:u/{sender['gmail_slot']}"
                else:
                    attachments, inline_attachments = _attachment_payloads(item["attachments"], item["body_html"])
                    raw = build_raw_message(
                        item["recipient"], item["subject"], item["body"], item["cc"], item["bcc"],
                        item["body_html"], attachments, inline_attachments
                    )
                    remote_id = await (create_draft(gmail_token or {}, raw) if mode == "draft" else send_message(gmail_token or {}, raw))
                store.update_item(item["id"], status="Success", remote_id=remote_id, increment_attempt=True)
                store.log_operation({**_operation_from_item(current, item, account_label), "remote_id": remote_id, "result": "Success", "error": ""})
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                error = _safe_error(exc)
                if status in {401, 403, 429} or status >= 500:
                    ambiguous = mode in {"send", "draft"} and status >= 500
                    item_status = "NeedsReview" if ambiguous else "Failed"
                    result = "Uncertain" if ambiguous else "Failed"
                    store.update_item(item["id"], status=item_status, error=error, increment_attempt=True)
                    store.log_operation({**_operation_from_item(current, item, account_label), "result": result, "error": error})
                    store.refresh_campaign_counts(campaign_id)
                    pause_error = (
                        f"Gmail {mode} outcome is uncertain; inspect Gmail before resolving this item. {error}"
                        if ambiguous else error
                    )
                    store.set_campaign_status(campaign_id, "Paused", error=pause_error)
                    return
                store.update_item(item["id"], status="Failed", error=error, increment_attempt=True)
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Failed", "error": error})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error = _safe_error(exc)
                if mode in {"send", "draft"}:
                    store.update_item(item["id"], status="NeedsReview", error=error, increment_attempt=True)
                    store.log_operation({**_operation_from_item(current, item, account_label), "result": "Uncertain", "error": error})
                    store.refresh_campaign_counts(campaign_id)
                    store.set_campaign_status(
                        campaign_id,
                        "Paused",
                        error=f"Gmail {mode} outcome is uncertain; inspect Gmail before resolving this item. {error}",
                    )
                    return
                store.update_item(item["id"], status="Failed", error=error, increment_attempt=True)
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Failed", "error": error})
            except Exception as exc:
                error = _safe_error(exc)
                store.update_item(item["id"], status="Failed", error=error, increment_attempt=True)
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Failed", "error": error})
            store.refresh_campaign_counts(campaign_id)
            if item_index + 1 < len(items):
                await asyncio.sleep(max(0, int(current.get("throttle_ms", 0))) / 1000)

        final = store.get_campaign(campaign_id)
        if final and final["status"] == "Running":
            if store.queue_items(campaign_id, statuses=("NeedsReview",)):
                store.set_campaign_status(campaign_id, "Paused", error="Resolve the uncertain Gmail outcome before continuing.")
                return
            store.refresh_campaign_counts(campaign_id)
            final = store.get_campaign(campaign_id)
            store.set_campaign_status(campaign_id, "CompletedWithErrors" if final and final["failed"] else "Completed")
    except asyncio.CancelledError:
        current = store.get_campaign(campaign_id)
        if current and current["status"] == "Running":
            store.set_campaign_status(campaign_id, "Paused", error="Processing was interrupted; review before resuming.")
        raise
    except Exception as exc:
        store.set_campaign_status(campaign_id, "Paused", error=_safe_error(exc))


def _operation_from_item(campaign: dict[str, Any], item: dict[str, Any], account: str) -> dict[str, Any]:
    return {
        "campaign_id": campaign["id"], "mode": campaign["mode"], "account": account,
        "row_number": item["row_number"], "recipient": item["recipient"], "subject": item["subject"],
        "fingerprint": item["fingerprint"], "remote_id": "",
    }


# ---------- common helpers ----------
async def _verified_google_account(email_address: str, require_scope: str = GMAIL_SCOPE) -> tuple[dict[str, Any], str]:
    try:
        account = store.get_account(email_address)
    except Exception as exc:
        raise RuntimeError("Stored Google credentials could not be read. Disconnect and reconnect this account.") from exc
    if not account:
        raise RuntimeError("The selected Google account is not connected.")
    token, client = account
    token = await refresh_token(token, client)
    if require_scope and not token_has_scope(token, require_scope):
        scope_name = "Google Sheets read-only" if require_scope == SHEETS_SCOPE else "Gmail compose"
        raise RuntimeError(f"This account is missing the {scope_name} permission. Reconnect it with the required access.")
    actual_email = await profile_email(token)
    if actual_email.casefold() != email_address.casefold():
        raise RuntimeError(f"Connected credential belongs to {actual_email}, not {email_address}.")
    store.save_account(actual_email, token, client)
    return token, actual_email


def _profile_for_sender(sender: dict[str, Any]) -> dict[str, Any]:
    profiles = discover_profiles()
    profile = next((p for p in profiles if p["browser_id"] == sender["browser_id"] and p["profile_dir"] == sender["profile_dir"]), None)
    if profile is None:
        raise HTTPException(400, "The browser profile for this sender route is no longer available.")
    return profile


def _require_fresh_browser_sender(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(400, "Select a saved browser sender route.")
    verified = sender.get("verified_at") or ""
    try:
        verified_dt = datetime.fromisoformat(verified)
    except (ValueError, TypeError):
        verified_dt = datetime.min.replace(tzinfo=timezone.utc)
    if verified_dt.tzinfo is None:
        verified_dt = verified_dt.replace(tzinfo=timezone.utc)
    if verified_dt < datetime.now(timezone.utc) - timedelta(minutes=BROWSER_VERIFICATION_MINUTES):
        raise HTTPException(409, f"Verify that Gmail /u/{sender['gmail_slot']}/ is {sender['expected_email']} before opening drafts.")
    _profile_for_sender(sender)
    return sender


def _validate_mapping_columns(payload: RenderRequest, headers: list[str]) -> None:
    required = [payload.to_column]
    optional = [payload.name_column, payload.cc_column, payload.bcc_column, payload.attachment_column, payload.filter_column, payload.sort_column]
    if any(column and column not in headers for column in required + optional):
        raise HTTPException(400, "A selected spreadsheet column no longer exists. Refresh the mapping.")
    if not payload.to_column:
        raise HTTPException(400, "Select a recipient email column.")


def _filter_row(value: str, operator: str, wanted: str) -> bool:
    value = (value or "").strip()
    wanted = (wanted or "").strip()
    if operator == "not_empty":
        return bool(value)
    if operator == "contains":
        return wanted.casefold() in value.casefold()
    return value.casefold() == wanted.casefold()


def _merge_addresses(left: str, right: str) -> str:
    values = split_addresses(left) + split_addresses(right)
    return ", ".join(dict.fromkeys(values))


def _normalize_schedule(value: str) -> str:
    if not value.strip():
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Scheduled time is invalid.") from exc
    if parsed.tzinfo is None:
        raise HTTPException(400, "Scheduled time must include a timezone.")
    parsed = parsed.astimezone(timezone.utc)
    if parsed <= datetime.now(timezone.utc) + timedelta(seconds=5):
        raise HTTPException(400, "Scheduled time must be at least 5 seconds in the future.")
    return parsed.isoformat(timespec="seconds")


def _cleanup_orphan_import_files() -> None:
    for path in imports_dir().iterdir():
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def _prune_imports() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=IMPORT_TTL_HOURS)
    for import_id, meta in list(imports.items()):
        try:
            snapshot_at = datetime.fromisoformat(str(meta.get("snapshot_at") or "").replace("Z", "+00:00"))
            if snapshot_at.tzinfo is None:
                snapshot_at = snapshot_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            snapshot_at = datetime.min.replace(tzinfo=timezone.utc)
        if snapshot_at < cutoff or not Path(meta["path"]).exists():
            try:
                Path(meta["path"]).unlink(missing_ok=True)
            except OSError:
                pass
            imports.pop(import_id, None)


def _import_meta(import_id: str) -> dict[str, Any]:
    _prune_imports()
    meta = imports.get(import_id)
    if meta is None or not Path(meta["path"]).exists():
        raise HTTPException(404, "Spreadsheet import expired. Load the source again.")
    return meta


def _import_path(import_id: str) -> Path:
    return Path(_import_meta(import_id)["path"])


def _public_import(meta: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in meta.items() if key != "path"}


def _require_campaign(campaign_id: str) -> dict[str, Any]:
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    return campaign


def _oauth_page(success: bool, message: str) -> HTMLResponse:
    safe = html.escape(message, quote=True)
    icon = "✓" if success else "!"
    return HTMLResponse(
        f"""<!doctype html><meta charset='utf-8'><title>MailDesk</title>
        <style>body{{font-family:system-ui;margin:0;display:grid;place-items:center;min-height:100vh;background:#f5f7fa;color:#17202a}}.card{{max-width:560px;background:white;border:1px solid #dfe5ec;border-radius:18px;padding:32px;box-shadow:0 16px 50px #15202b18}}.icon{{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:#e9f7ef;margin-bottom:18px;font-weight:800}}</style>
        <div class='card'><div class='icon'>{icon}</div><h2>{'Connected' if success else 'Connection problem'}</h2><p>{safe}</p><p>You may close this tab and return to MailDesk.</p></div>"""
    )


def _prune_oauth_sessions() -> None:
    cutoff = time.time() - 600
    for key in [key for key, value in oauth_sessions.items() if value.get("created", 0) < cutoff]:
        oauth_sessions.pop(key, None)


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(access_token|refresh_token|client_secret)[=:]\s*[^\s,}]+", r"\1=[REDACTED]", text)
    return text[:2000]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run() -> None:
    lock = acquire_instance_lock()
    if lock is None:
        raise RuntimeError("Another MailDesk instance is already running on this machine.")
    try:
        host = "127.0.0.1"
        port = int(os.getenv("MAILMERGE_PORT", "8765"))
        url = f"http://{host}:{port}/"
        if os.getenv("MAILMERGE_NO_BROWSER") != "1":
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        lock.close()


if __name__ == "__main__":
    run()
