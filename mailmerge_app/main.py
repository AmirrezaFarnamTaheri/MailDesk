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
    revoke_token,
    send_message,
    spreadsheet_id_from_url,
    token_has_scope,
    token_health,
    token_is_valid,
)
from .google_sheets import snapshot_spreadsheet
from .instance import acquire_instance_lock
from .paths import attachments_dir, imports_dir
from .sheet_reader import SUPPORTED_EXTENSIONS, column_profiles, list_sheets, suggest_mappings, table
from .storage import Store
from .template_engine import batch_fingerprint, html_to_text, is_valid_email, message_fingerprint, render_text, split_addresses

APP_VERSION = "0.3.1"
STATIC_DIR = Path(__file__).with_name("static")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENT_NAME_CHARS = 255
MAX_OAUTH_CLIENT_BYTES = 2 * 1024 * 1024
ATTACHMENT_CACHE_MAX_ENTRIES = 8
ATTACHMENT_CACHE_MAX_ITEM_BYTES = 8 * 1024 * 1024
BLOCKED_ATTACHMENT_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".jar"}
BROWSER_VERIFICATION_MINUTES = 30
IMPORT_TTL_HOURS = 24
OAUTH_SESSION_TTL_SECONDS = 600
OAUTH_SESSION_MAX = 32

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
    if request.url.path.startswith("/oauth/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
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
    selected_rows: list[str] | None = Field(default=None, max_length=100_000)
    row_overrides: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100_000)
    limit: int = Field(default=0, ge=0, le=100_000)
    trim_values: bool = True
    placeholder_mappings: dict[str, str] = Field(default_factory=dict, max_length=200)


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
        raise HTTPException(400, "Template id does not match the request path.")
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
        raise HTTPException(400, "Snippet id does not match the request path.")
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
    if not filename or len(filename) > MAX_ATTACHMENT_NAME_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in filename):
        raise HTTPException(400, "Attachment filename is invalid or too long.")
    suffix = Path(filename).suffix.lower()
    if suffix in BLOCKED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(400, "Executable/script attachments are blocked by MailDesk.")
    # The stored filename is app-generated and never needs an arbitrary long or
    # unusual extension from user input. Bounding it avoids Windows path-component
    # failures while the original display filename remains in metadata.
    stored_suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,19}", suffix) else ""
    attachment_id = uuid.uuid4().hex
    stored_name = f"{attachment_id}{stored_suffix}"
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
    try:
        path = _attachment_file(item)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
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
        sheets = await asyncio.to_thread(list_sheets, path)
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
        headers, rows, detected, profiles, suggestions = await asyncio.to_thread(_preview_source, path, sheet, header_row)
    except Exception as exc:
        raise HTTPException(400, _safe_error(exc)) from exc
    return {
        "headers": headers,
        "header_row": detected,
        "total_rows": len(rows),
        "rows": rows[:100],
        "row_numbers": [row.get("_row", "") for row in rows],
        "column_profiles": profiles,
        "suggestions": suggestions,
        "source": _public_import(_import_meta(import_id)),
    }


@app.get("/api/imports/{import_id}/rows")
async def import_rows(
    import_id: str,
    sheet: str = Query(...),
    header_row: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    q: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    path = _import_path(import_id)
    try:
        headers, rows, detected = await asyncio.to_thread(table, path, sheet, header_row)
    except Exception as exc:
        raise HTTPException(400, _safe_error(exc)) from exc
    query = q.strip().casefold()
    if query:
        rows = [
            row for row in rows
            if query in str(row.get("_row", "")).casefold()
            or any(query in str(row.get(header, "")).casefold() for header in headers)
        ]
    total = len(rows)
    page = rows[offset: offset + limit]
    return {
        "headers": headers,
        "header_row": detected,
        "total": total,
        "offset": offset,
        "limit": limit,
        "rows": page,
        "source": _public_import(_import_meta(import_id)),
    }


@app.post("/api/render")
async def render_messages(payload: RenderRequest) -> dict[str, Any]:
    path = _import_path(payload.import_id)
    try:
        headers, rows, detected = await asyncio.to_thread(table, path, payload.sheet, payload.header_row)
    except Exception as exc:
        raise HTTPException(400, _safe_error(exc)) from exc
    _validate_mapping_columns(payload, headers)

    if payload.selected_rows is not None:
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

    attachment_items = store.list_attachments()
    attachment_catalog = {item["id"]: item for item in attachment_items}
    attachment_by_name = {item["name"].casefold(): item["id"] for item in reversed(attachment_items)}
    messages = await asyncio.to_thread(_render_rows, payload, rows, attachment_by_name, attachment_catalog)
    invalid = sum(bool(message["errors"]) for message in messages)
    warnings = sum(bool(message["warnings"]) for message in messages)
    batch_id = await asyncio.to_thread(batch_fingerprint, messages)
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
    fingerprint = await asyncio.to_thread(batch_fingerprint, [message.model_dump() for message in payload.messages])
    return {"batch_id": fingerprint}


# ---------- browser profiles and Gmail account slots ----------
@app.get("/api/browser-profiles")
async def browser_profiles(refresh: bool = Query(default=False)) -> list[dict[str, object]]:
    return await asyncio.to_thread(discover_profiles, force_refresh=refresh)


@app.get("/api/browser-senders")
async def browser_senders_list() -> list[dict[str, Any]]:
    return store.list_browser_senders()


@app.put("/api/browser-senders/{sender_id}")
async def browser_sender_save(sender_id: str, payload: BrowserSenderPayload) -> dict[str, Any]:
    if payload.id and payload.id != sender_id:
        raise HTTPException(400, "Browser sender id does not match the request path.")
    if not is_valid_email(payload.expected_email):
        raise HTTPException(400, "Expected sender email is invalid.")
    profiles = await asyncio.to_thread(discover_profiles, force_refresh=True)
    selected = next((p for p in profiles if p["browser_id"] == payload.browser_id and p["profile_dir"] == payload.profile_dir), None)
    if selected is None:
        raise HTTPException(400, "The selected browser profile is not currently available.")
    detected_accounts = selected.get("gmail_accounts") if isinstance(selected, dict) else []
    if isinstance(detected_accounts, list) and detected_accounts:
        detected = next((a for a in detected_accounts if int(a.get("slot", -1)) == payload.gmail_slot), None)
        if detected is None:
            raise HTTPException(409, f"The browser cache has no Gmail account at index {payload.gmail_slot}. Rescan and choose a detected account.")
        detected_email = str(detected.get("email") or "")
        if detected_email.casefold() != payload.expected_email.strip().casefold():
            raise HTTPException(409, f"Browser account {payload.gmail_slot} is currently cached as {detected_email}, not {payload.expected_email}. Rescan or choose the matching account.")
    existing = store.get_browser_sender(sender_id)
    item = payload.model_dump()
    item["id"] = sender_id
    if existing and any(str(existing.get(key)) != str(item.get(key)) for key in ("browser_id", "profile_dir", "gmail_slot", "expected_email")):
        item["verified_at"] = ""
    return store.save_browser_sender(item)


@app.delete("/api/browser-senders/{sender_id}")
async def browser_sender_delete(sender_id: str) -> dict[str, bool]:
    if store.browser_sender_in_use(sender_id):
        raise HTTPException(409, "This browser sender is used by an active campaign. Cancel or finish that campaign first.")
    store.delete_browser_sender(sender_id)
    return {"deleted": True}


@app.post("/api/browser-senders/{sender_id}/verify/open")
async def browser_sender_verify_open(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(404, "Browser sender not found.")
    profiles = await asyncio.to_thread(discover_profiles, force_refresh=True)
    profile = next((p for p in profiles if p["browser_id"] == sender["browser_id"] and p["profile_dir"] == sender["profile_dir"]), None)
    if profile is None:
        raise HTTPException(409, "The saved browser profile is no longer available. Rescan browsers and update this sender.")
    slot = int(sender["gmail_slot"])
    expected = str(sender["expected_email"])
    accounts = profile.get("gmail_accounts") if isinstance(profile, dict) else []
    detected_email = ""
    if isinstance(accounts, list) and accounts:
        detected = next((a for a in accounts if int(a.get("slot", -1)) == slot), None)
        if detected is None:
            raise HTTPException(409, f"Gmail account index {slot} is no longer present in this browser profile. Rescan and update the sender.")
        detected_email = str(detected.get("email") or "")
        if detected_email.casefold() != expected.casefold():
            raise HTTPException(409, f"Browser account {slot} now maps to {detected_email}, not {expected}. Update the sender before continuing.")
    launch_url(profile, inbox_url(slot))
    return {
        "opened": True,
        "expected_email": expected,
        "detected_email": detected_email,
        "gmail_slot": slot,
        "session_cache_age_seconds": profile.get("session_cache_age_seconds"),
    }


@app.post("/api/browser-senders/{sender_id}/verify/confirm")
async def browser_sender_verify_confirm(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(404, "Browser sender not found.")
    store.mark_browser_sender_verified(sender_id)
    return store.get_browser_sender(sender_id) or {}


# ---------- Google accounts ----------
@app.get("/api/oauth/google/client")
async def google_client_status() -> dict[str, Any]:
    return _google_client_status()


@app.post("/api/oauth/google/client")
async def google_client_save(client_secret: UploadFile = File(...)) -> dict[str, Any]:
    client = await _read_google_oauth_client(client_secret)
    store.save_oauth_client("google", client)
    return _google_client_status()


@app.delete("/api/oauth/google/client")
async def google_client_delete() -> dict[str, bool]:
    store.delete_oauth_client("google")
    return {"deleted": True}


@app.get("/api/accounts")
async def accounts_list() -> list[dict[str, Any]]:
    output = []
    for item in store.list_accounts():
        try:
            account = store.get_account(item["email"])
            token = account[0] if account else {}
            health = token_health(token)
            scopes = set(health["scopes"])
            output.append({
                **item,
                "gmail": GMAIL_SCOPE in scopes,
                "sheets": SHEETS_SCOPE in scopes,
                "credential_error": "",
                "access_valid": health["access_valid"],
                "refresh_available": health["refresh_available"],
                "expires_at": health["expires_at"],
            })
        except Exception:
            output.append({
                **item,
                "gmail": False,
                "sheets": False,
                "credential_error": "Stored credentials could not be read. Reconnect this account.",
                "access_valid": False,
                "refresh_available": False,
                "expires_at": "",
            })
    return output


@app.post("/api/accounts/google/start")
async def google_start(
    request: Request,
    client_secret: UploadFile | None = File(None),
    include_sheets: bool = Form(True),
) -> dict[str, str]:
    client = await _resolve_google_oauth_client(client_secret)
    return _begin_google_oauth(request, client, include_sheets=include_sheets)


@app.post("/api/accounts/{email}/reconnect")
async def google_reconnect(request: Request, email: str, include_sheets: bool = Form(True)) -> dict[str, str]:
    existing = None
    try:
        existing = store.get_account(email)
    except Exception:
        existing = None
    client = existing[1] if existing else store.get_oauth_client("google")
    if not client:
        raise HTTPException(400, "No reusable Google OAuth client is configured. Upload the Desktop app client JSON first.")
    existing_token = existing[0] if existing else {}
    keep_sheets = include_sheets or token_has_scope(existing_token, SHEETS_SCOPE)
    return _begin_google_oauth(
        request,
        client,
        include_sheets=keep_sheets,
        login_hint=email,
        expected_email=email,
        prompt="consent",
    )


@app.post("/api/accounts/{email}/check")
async def google_account_check(email: str) -> dict[str, Any]:
    try:
        token, actual = await _verified_google_account(email, require_scope=GMAIL_SCOPE)
    except Exception as exc:
        raise HTTPException(409, _safe_error(exc)) from exc
    health = token_health(token)
    scopes = set(health["scopes"])
    return {
        "email": actual,
        "gmail": GMAIL_SCOPE in scopes,
        "sheets": SHEETS_SCOPE in scopes,
        "access_valid": health["access_valid"],
        "refresh_available": health["refresh_available"],
        "expires_at": health["expires_at"],
    }


@app.post("/api/accounts/{email}/revoke")
async def google_account_revoke(email: str) -> dict[str, bool]:
    if store.account_in_use(email):
        raise HTTPException(409, "This Google account is used by an active campaign. Cancel or finish that campaign first.")
    try:
        account = store.get_account(email)
    except Exception as exc:
        raise HTTPException(409, "Stored credentials could not be read. Disconnect locally instead.") from exc
    if account:
        try:
            await revoke_token(account[0])
        except Exception as exc:
            raise HTTPException(502, _safe_error(exc)) from exc
    store.delete_account(email)
    return {"revoked": True}


@app.get("/oauth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    # State is required for both successful and failed authorization responses.
    # Consume it exactly once so a stale/cancelled callback cannot be replayed.
    session = oauth_sessions.pop(state, None) if state else None
    if not session or time.time() - session.get("created", 0) > OAUTH_SESSION_TTL_SECONDS:
        return _oauth_page(False, "Authorization session expired or could not be verified. Return to MailDesk and connect again.")
    if error:
        if error == "access_denied":
            return _oauth_page(False, "Google authorization was cancelled or denied. No account was changed.")
        safe_error = re.sub(r"[^a-zA-Z0-9_.-]", "", error)[:80] or "authorization_error"
        return _oauth_page(False, f"Google authorization failed: {safe_error}")
    if not code:
        return _oauth_page(False, "Google did not return an authorization code.")
    try:
        token = await exchange_code(session["client"], code, session["verifier"], session["redirect_uri"])
        token["scope"] = token.get("scope") or session.get("requested_scopes", "")
        email_address = await profile_email(token)
        expected_email = str(session.get("expected_email") or "").strip()
        if expected_email and email_address.casefold() != expected_email.casefold():
            return _oauth_page(False, f"Google connected {email_address}, but MailDesk was reconnecting {expected_email}. No account was changed.")
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
    max_batch = int(store.get_setting("max_batch_size", "500") or "500")
    if len(payload.messages) > max_batch:
        raise HTTPException(400, f"Batch has {len(payload.messages)} messages; maximum is {max_batch}.")
    await asyncio.to_thread(_validate_campaign_messages, payload.messages)
    expected_batch = await asyncio.to_thread(batch_fingerprint, [m.model_dump() for m in payload.messages])
    if payload.batch_id != expected_batch:
        raise HTTPException(409, "Messages changed. Check the current messages again before processing.")

    if payload.mode == "send":
        expected = f"SEND {len(payload.messages)}"
        if payload.confirm_text.strip() != expected:
            raise HTTPException(400, f"Sending requires typing exactly: {expected}")
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
    campaign = await asyncio.to_thread(
        store.create_campaign,
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


@app.get("/api/campaigns/{campaign_id}/detail")
async def campaign_detail(
    campaign_id: str,
    limit: int = Query(default=500, ge=1, le=1000),
    needs_review_limit: int = Query(default=500, ge=1, le=1000),
) -> dict[str, Any]:
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    items, review_total = await asyncio.to_thread(_queue_item_summaries, campaign_id, limit, needs_review_limit)
    return {**campaign, "items": items, "visible_items": len(items), "needs_review_total": review_total}


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
    path = await asyncio.to_thread(store.backup)
    return {"backup": str(path)}


# ---------- rendering helpers ----------
def _preview_source(path: Path, sheet: str, header_row: int | None) -> tuple[list[str], list[dict[str, str]], int, list[dict[str, Any]], dict[str, str]]:
    headers, rows, detected = table(path, sheet, header_row)
    return headers, rows, detected, column_profiles(headers, rows), suggest_mappings(headers, rows)


def _render_rows(
    payload: RenderRequest,
    rows: list[dict[str, str]],
    attachment_by_name: dict[str, str],
    attachment_catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    messages = [_render_row(payload, row, attachment_by_name, attachment_catalog) for row in rows]
    _mark_duplicate_recipients(messages)
    return messages


def _render_row(
    payload: RenderRequest,
    row: dict[str, str],
    attachment_by_name: dict[str, str],
    attachment_catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    working = {key: (value.strip() if payload.trim_values and isinstance(value, str) else value) for key, value in row.items()}
    for placeholder, column in payload.placeholder_mappings.items():
        if placeholder not in {"_row", "_today"} and column:
            working[placeholder] = working.get(column, "")
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
    if "\r" in subject.text or "\n" in subject.text:
        errors.append("Subject contains a line break.")
    if not subject.text.strip():
        warnings.append("Subject is blank.")
    if not body.text.strip() and not body_html:
        warnings.append("Body is blank.")

    attachment_ids = list(dict.fromkeys(payload.attachment_ids))
    catalog = attachment_catalog if attachment_catalog is not None else {item["id"]: item for item in store.list_attachments()}
    if payload.attachment_column:
        raw_attachments = str(working.get(payload.attachment_column, ""))
        for value in [part.strip() for part in re.split(r"[;,\n]+", raw_attachments) if part.strip()]:
            if value in catalog:
                attachment_ids.append(value)
            elif value.casefold() in attachment_by_name:
                attachment_ids.append(attachment_by_name[value.casefold()])
            else:
                errors.append(f"Attachment not found in app library: {value}")
    attachment_ids = list(dict.fromkeys(attachment_ids))
    try:
        _validate_attachment_ids(attachment_ids, catalog)
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


def _validate_campaign_messages(messages: list[MessagePayload]) -> None:
    if not messages:
        raise HTTPException(400, "There are no messages to process.")
    invalid_rows = [message.row_number for message in messages if message.errors]
    if invalid_rows:
        raise HTTPException(400, "Fix validation errors before processing rows: " + ", ".join(invalid_rows[:12]))
    attachment_catalog = {item["id"]: item for item in store.list_attachments()}
    for message in messages:
        recipients = split_addresses(message.to)
        if not recipients:
            raise HTTPException(400, f"Recipient is blank in row {message.row_number}.")
        for address in recipients + split_addresses(message.cc) + split_addresses(message.bcc):
            if not is_valid_email(address):
                raise HTTPException(400, f"Invalid email address in row {message.row_number}: {address}")
        if "\r" in message.subject or "\n" in message.subject:
            raise HTTPException(400, f"Subject contains a line break in row {message.row_number}.")
        _validate_attachment_ids(message.attachments, attachment_catalog)


def _attachment_file(item: dict[str, Any]) -> Path:
    base = attachments_dir().resolve()
    stored_name = str(item.get("stored_name") or "")
    component = Path(stored_name)
    if not stored_name or component.is_absolute() or component.name != stored_name:
        raise RuntimeError("Attachment storage path is invalid. Remove and re-add the attachment.")
    path = base / stored_name
    try:
        if path.is_symlink():
            raise RuntimeError("Attachment file was replaced by a symbolic link. Remove and re-add it.")
        resolved = path.resolve(strict=True)
        if resolved.parent != base or not resolved.is_file():
            raise RuntimeError("Attachment file is outside the MailDesk attachment store.")
        actual_size = resolved.stat().st_size
    except FileNotFoundError as exc:
        raise RuntimeError(f"Attachment file is missing: {item.get('name') or stored_name}") from exc
    except OSError as exc:
        raise RuntimeError(f"Attachment file could not be verified: {item.get('name') or stored_name}") from exc
    expected_size = int(item.get("size") or 0)
    if actual_size != expected_size:
        raise RuntimeError(f"Attachment file changed after it was added: {item.get('name') or stored_name}. Remove and re-add it.")
    return resolved


def _validate_attachment_ids(ids: list[str], catalog: dict[str, dict[str, Any]] | None = None) -> None:
    total = 0
    missing: list[str] = []
    attachment_catalog = catalog if catalog is not None else {item["id"]: item for item in store.list_attachments()}
    for attachment_id in ids:
        item = attachment_catalog.get(attachment_id)
        if not item:
            missing.append(attachment_id)
            continue
        try:
            _attachment_file(item)
        except RuntimeError:
            missing.append(attachment_id)
            continue
        total += int(item["size"])
    if missing:
        raise HTTPException(400, "Missing or changed attachment(s): " + ", ".join(missing[:8]))
    if total > 24 * 1024 * 1024:
        raise HTTPException(400, "Selected attachments exceed the 24 MB pre-encoding limit.")


def _attachment_payloads(
    ids: list[str],
    body_html: str = "",
    cache: dict[str, tuple[str, bytes, str | None]] | None = None,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[tuple[str, bytes, str | None]], list[tuple[str, str, bytes, str | None]]]:
    regular: list[tuple[str, bytes, str | None]] = []
    inline: list[tuple[str, str, bytes, str | None]] = []
    attachment_catalog = catalog if catalog is not None else {item["id"]: item for item in store.list_attachments()}
    for attachment_id in ids:
        cached = cache.get(attachment_id) if cache is not None else None
        if cached is not None:
            name, payload, mime_type = cached
        else:
            item = attachment_catalog.get(attachment_id)
            if not item:
                raise RuntimeError(f"Attachment disappeared: {attachment_id}")
            path = _attachment_file(item)
            payload = path.read_bytes()
            name = item["name"]
            mime_type = item.get("mime_type") or mimetypes.guess_type(name)[0]
            if (
                cache is not None
                and len(payload) <= ATTACHMENT_CACHE_MAX_ITEM_BYTES
                and len(cache) < ATTACHMENT_CACHE_MAX_ENTRIES
            ):
                cache[attachment_id] = (name, payload, mime_type)
        if f"cid:{attachment_id}" in (body_html or "") and str(mime_type or "").startswith("image/"):
            inline.append((attachment_id, name, payload, mime_type))
        else:
            regular.append((name, payload, mime_type))
    return regular, inline


def _queue_item_summaries(campaign_id: str, limit: int, needs_review_limit: int) -> tuple[list[dict[str, Any]], int]:
    columns = "id,ordinal,row_number,recipient,subject,status,attempts,error"
    with store._db() as db:
        normal = [dict(row) for row in db.execute(
            f"SELECT {columns} FROM queue_items WHERE campaign_id=? ORDER BY ordinal LIMIT ?",
            (campaign_id, limit),
        ).fetchall()]
        review_total = int(db.execute(
            "SELECT COUNT(*) n FROM queue_items WHERE campaign_id=? AND status='NeedsReview'",
            (campaign_id,),
        ).fetchone()["n"])
        review = [dict(row) for row in db.execute(
            f"SELECT {columns} FROM queue_items WHERE campaign_id=? AND status='NeedsReview' ORDER BY ordinal LIMIT ?",
            (campaign_id, needs_review_limit),
        ).fetchall()]
    seen = {item["id"] for item in normal}
    normal.extend(item for item in review if item["id"] not in seen)
    return normal, review_total


def _successful_fingerprints(fingerprints: list[str]) -> set[str]:
    unique = list(dict.fromkeys(fp for fp in fingerprints if fp))
    found: set[str] = set()
    if not unique:
        return found
    # Each chunk is bound twice (operations + durable outbox), so keep below
    # SQLite's traditional 999-variable ceiling even on older bundled builds.
    with store._db() as db:
        for start in range(0, len(unique), 400):
            chunk = unique[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = db.execute(
                f"""SELECT fingerprint FROM operations
                    WHERE result='Success' AND fingerprint IN ({placeholders})
                    UNION
                    SELECT fingerprint FROM operation_outbox
                    WHERE status='Success' AND fingerprint IN ({placeholders})""",
                (*chunk, *chunk),
            ).fetchall()
            found.update(str(row["fingerprint"]) for row in rows)
    return found


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
    gmail_http: httpx.AsyncClient | None = None
    attachment_cache: dict[str, tuple[str, bytes, str | None]] = {}
    attachment_catalog = {item["id"]: item for item in store.list_attachments()}
    try:
        if mode == "browser":
            sender = _require_fresh_browser_sender(campaign["browser_sender_id"])
            browser_profile = _profile_for_sender(sender)
            account_label = sender["expected_email"]
        elif mode in {"draft", "send"}:
            gmail_token, actual = await _verified_google_account(campaign["account"], require_scope=GMAIL_SCOPE)
            account_label = actual
            # One pool per campaign avoids repeated DNS/TLS/socket setup for every
            # message while keeping the client's lifetime explicit and bounded.
            gmail_http = httpx.AsyncClient(timeout=30)
        store.set_campaign_status(campaign_id, "Running")

        items = store.queue_items(campaign_id)
        skip_duplicates = bool(int(campaign.get("skip_duplicates", 1)))
        successful_fingerprints = (
            await asyncio.to_thread(_successful_fingerprints, [item["fingerprint"] for item in items])
            if skip_duplicates else set()
        )
        for item_index, item in enumerate(items):
            current = store.get_campaign(campaign_id)
            if not current or current["status"] in {"Paused", "Cancelled"}:
                return
            if skip_duplicates and item["fingerprint"] in successful_fingerprints:
                store.update_item(item["id"], status="Skipped", error="Already processed successfully.")
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Skipped", "error": "Already processed successfully."})
                store.refresh_campaign_counts(campaign_id)
                continue

            if mode in {"draft", "send"} and not token_is_valid(gmail_token or {}, margin_seconds=120):
                gmail_token, actual = await _verified_google_account(current["account"], require_scope=GMAIL_SCOPE)
                account_label = actual

            try:
                remote_id = ""
                attempt_recorded = False
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
                    attachments, inline_attachments = await asyncio.to_thread(
                        _attachment_payloads,
                        item["attachments"],
                        item["body_html"],
                        attachment_cache,
                        attachment_catalog,
                    )
                    raw = await asyncio.to_thread(
                        build_raw_message,
                        item["recipient"], item["subject"], item["body"], item["cc"], item["bcc"],
                        item["body_html"], attachments, inline_attachments,
                    )
                    if gmail_http is None:
                        raise RuntimeError("Gmail HTTP client was not initialized.")
                    store.update_item(item["id"], status="InFlight", increment_attempt=True)
                    attempt_recorded = True
                    remote_id = await (
                        create_draft(gmail_token or {}, raw, http=gmail_http)
                        if mode == "draft"
                        else send_message(gmail_token or {}, raw, http=gmail_http)
                    )
                store.update_item(item["id"], status="Success", remote_id=remote_id, increment_attempt=not attempt_recorded)
                store.log_operation({**_operation_from_item(current, item, account_label), "remote_id": remote_id, "result": "Success", "error": ""})
                successful_fingerprints.add(item["fingerprint"])
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                error = _safe_error(exc)
                if status in {401, 403, 429} or status >= 500:
                    ambiguous = mode in {"send", "draft"} and status >= 500
                    item_status = "NeedsReview" if ambiguous else "Failed"
                    result = "Uncertain" if ambiguous else "Failed"
                    store.update_item(item["id"], status=item_status, error=error, increment_attempt=not attempt_recorded)
                    store.log_operation({**_operation_from_item(current, item, account_label), "result": result, "error": error})
                    store.refresh_campaign_counts(campaign_id)
                    pause_error = (
                        f"Gmail {mode} outcome is uncertain; inspect Gmail before resolving this item. {error}"
                        if ambiguous else error
                    )
                    store.set_campaign_status(campaign_id, "Paused", error=pause_error)
                    return
                store.update_item(item["id"], status="Failed", error=error, increment_attempt=not attempt_recorded)
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Failed", "error": error})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error = _safe_error(exc)
                if mode in {"send", "draft"}:
                    store.update_item(item["id"], status="NeedsReview", error=error, increment_attempt=not attempt_recorded)
                    store.log_operation({**_operation_from_item(current, item, account_label), "result": "Uncertain", "error": error})
                    store.refresh_campaign_counts(campaign_id)
                    store.set_campaign_status(
                        campaign_id,
                        "Paused",
                        error=f"Gmail {mode} outcome is uncertain; inspect Gmail before resolving this item. {error}",
                    )
                    return
                store.update_item(item["id"], status="Failed", error=error, increment_attempt=not attempt_recorded)
                store.log_operation({**_operation_from_item(current, item, account_label), "result": "Failed", "error": error})
            except Exception as exc:
                error = _safe_error(exc)
                store.update_item(item["id"], status="Failed", error=error, increment_attempt=not attempt_recorded)
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
    finally:
        if gmail_http is not None:
            try:
                await gmail_http.aclose()
            except Exception:
                pass


def _operation_from_item(campaign: dict[str, Any], item: dict[str, Any], account: str) -> dict[str, Any]:
    return {
        "campaign_id": campaign["id"], "mode": campaign["mode"], "account": account,
        "row_number": item["row_number"], "recipient": item["recipient"], "subject": item["subject"],
        "fingerprint": item["fingerprint"], "remote_id": "",
    }


# ---------- common helpers ----------
def _google_client_status() -> dict[str, Any]:
    try:
        info = store.get_oauth_client_info("google")
    except Exception:
        return {"configured": False, "client_id_hint": "", "updated_at": "", "credential_error": "Saved OAuth client could not be read. Replace it with a fresh Desktop app JSON file.", "oauth_version": "2.0", "pkce": True, "redirect_mode": "loopback"}
    if not info:
        return {"configured": False, "client_id_hint": "", "updated_at": "", "credential_error": "", "oauth_version": "2.0", "pkce": True, "redirect_mode": "loopback"}
    client_id = str(info["client"].get("client_id") or "")
    if len(client_id) > 28:
        hint = f"{client_id[:10]}…{client_id[-16:]}"
    else:
        hint = client_id
    return {"configured": bool(client_id), "client_id_hint": hint, "updated_at": info["updated_at"], "credential_error": "", "oauth_version": "2.0", "pkce": True, "redirect_mode": "loopback"}


async def _read_google_oauth_client(upload: UploadFile) -> dict[str, str]:
    raw = await upload.read(MAX_OAUTH_CLIENT_BYTES + 1)
    if not raw:
        raise HTTPException(400, "OAuth client JSON is empty.")
    if len(raw) > MAX_OAUTH_CLIENT_BYTES:
        raise HTTPException(413, "OAuth client JSON is larger than 2 MB.")
    try:
        return parse_client_secret(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _resolve_google_oauth_client(upload: UploadFile | None) -> dict[str, str]:
    if upload is not None and upload.filename:
        client = await _read_google_oauth_client(upload)
        store.save_oauth_client("google", client)
        return client
    try:
        client = store.get_oauth_client("google")
    except Exception as exc:
        raise HTTPException(409, "Saved Google OAuth client could not be read. Replace the Desktop app JSON file.") from exc
    if not client:
        raise HTTPException(400, "Set up Google OAuth first by choosing a Desktop app client JSON file.")
    return {str(key): str(value) for key, value in client.items() if key in {"client_id", "client_secret"} and value}


def _begin_google_oauth(
    request: Request,
    client: dict[str, str],
    *,
    include_sheets: bool,
    login_hint: str = "",
    expected_email: str = "",
    prompt: str = "consent select_account",
) -> dict[str, str]:
    redirect_uri = _oauth_redirect_uri(request)
    scopes = [GMAIL_SCOPE] + ([SHEETS_SCOPE] if include_sheets else [])
    auth_url, session = new_oauth_request(
        client,
        redirect_uri,
        scopes=scopes,
        login_hint=login_hint,
        prompt=prompt,
    )
    oauth_sessions[session["state"]] = {
        **session,
        "client": client,
        "created": time.time(),
        "expected_email": expected_email.strip(),
    }
    _prune_oauth_sessions()
    return {"auth_url": auth_url}


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
        raise HTTPException(400, "The browser profile for this sender is no longer available.")
    return profile


def _require_fresh_browser_sender(sender_id: str) -> dict[str, Any]:
    sender = store.get_browser_sender(sender_id)
    if not sender:
        raise HTTPException(400, "Select a saved browser sender.")
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
    mapped = list(payload.placeholder_mappings.values())
    if any(column and column not in headers for column in required + optional + mapped):
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


def _oauth_redirect_uri(request: Request) -> str:
    """Build the OAuth callback from the actual loopback listener, not Host input.

    Native-app OAuth redirects are security-sensitive. Uvicorn exposes the bound
    listener in the ASGI scope, so use that port and always force the loopback IP
    literal recommended for desktop OAuth. TestClient is kept as a special local
    harness because it has no real loopback listener.
    """

    server = request.scope.get("server")
    if isinstance(server, (tuple, list)) and len(server) >= 2:
        host, port = server[0], server[1]
        if host == "testserver":
            return "http://testserver/oauth/google/callback"
        try:
            port_number = int(port)
        except (TypeError, ValueError):
            port_number = 8765
    else:
        port_number = int(os.getenv("MAILMERGE_PORT", "8765"))
    return f"http://127.0.0.1:{port_number}/oauth/google/callback"


def _prune_oauth_sessions() -> None:
    cutoff = time.time() - OAUTH_SESSION_TTL_SECONDS
    for key in [key for key, value in oauth_sessions.items() if value.get("created", 0) < cutoff]:
        oauth_sessions.pop(key, None)
    if len(oauth_sessions) > OAUTH_SESSION_MAX:
        oldest = sorted(oauth_sessions.items(), key=lambda item: float(item[1].get("created", 0)))
        for key, _value in oldest[: len(oauth_sessions) - OAUTH_SESSION_MAX]:
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
