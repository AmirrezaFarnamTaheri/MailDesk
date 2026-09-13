from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode

import httpx

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def parse_client_secret(document: bytes) -> dict[str, str]:
    try:
        parsed = json.loads(document.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The OAuth client JSON is not valid JSON.") from exc
    if "web" in parsed:
        raise ValueError("Use a Google OAuth client of type Desktop app, not Web application.")
    installed = parsed.get("installed")
    if not isinstance(installed, dict) or not installed.get("client_id") or not installed.get("client_secret"):
        raise ValueError("The file is not a valid Google Desktop app OAuth client JSON.")
    return {"client_id": installed["client_id"], "client_secret": installed["client_secret"]}


def new_oauth_request(
    client: dict[str, str],
    redirect_uri: str,
    scopes: Iterable[str] | None = None,
) -> tuple[str, dict[str, str]]:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    scope_list = list(scopes or [GMAIL_SCOPE])
    query = urlencode(
        {
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scope_list),
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTH_URL}?{query}", {
        "state": state,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "requested_scopes": " ".join(scope_list),
    }


async def exchange_code(client: dict[str, str], code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        token = response.json()
    token["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)) - 60)).isoformat()
    return token


async def refresh_token(token: dict[str, Any], client: dict[str, str]) -> dict[str, Any]:
    if _token_valid(token):
        return token
    refresh = token.get("refresh_token")
    if not refresh:
        raise RuntimeError("This Google account has no refresh token. Reconnect the account.")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        updated = response.json()
    updated["refresh_token"] = refresh
    updated["scope"] = updated.get("scope") or token.get("scope", "")
    updated["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(updated.get("expires_in", 3600)) - 60)).isoformat()
    return updated


async def profile_email(token: dict[str, Any]) -> str:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(f"{GMAIL_BASE}/profile", headers=_auth_header(token))
        response.raise_for_status()
        return str(response.json()["emailAddress"])


def token_has_scope(token: dict[str, Any], scope: str) -> bool:
    scopes = str(token.get("scope") or "").split()
    return scope in scopes


def build_raw_message(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    body_html: str = "",
    attachments: list[tuple[str, bytes, str | None]] | None = None,
    inline_attachments: list[tuple[str, str, bytes, str | None]] | None = None,
) -> str:
    message = EmailMessage()
    message["To"] = to
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    message["Subject"] = subject
    message.set_content(body or "")
    if body_html:
        message.add_alternative(body_html, subtype="html")
        html_part = message.get_payload()[-1]
        for content_id, filename, payload, content_type in inline_attachments or []:
            guessed = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            maintype, subtype = guessed.split("/", 1)
            html_part.add_related(
                payload, maintype=maintype, subtype=subtype, cid=f"<{content_id}>",
                filename=filename, disposition="inline"
            )
    for filename, payload, content_type in attachments or []:
        guessed = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        maintype, subtype = guessed.split("/", 1)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


async def create_draft(token: dict[str, Any], raw_message: str) -> str:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            f"{GMAIL_BASE}/drafts",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"message": {"raw": raw_message}},
        )
        response.raise_for_status()
        return str(response.json().get("id", ""))


async def send_message(token: dict[str, Any], raw_message: str) -> str:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            f"{GMAIL_BASE}/messages/send",
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json={"raw": raw_message},
        )
        response.raise_for_status()
        return str(response.json().get("id", ""))


async def google_sheet_metadata(token: dict[str, Any], spreadsheet_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(
            f"{SHEETS_BASE}/{spreadsheet_id}",
            params={"includeGridData": "false", "fields": "properties.title,sheets.properties"},
            headers=_auth_header(token),
        )
        response.raise_for_status()
        return response.json()


async def google_sheet_values(token: dict[str, Any], spreadsheet_id: str, sheet_title: str) -> list[list[Any]]:
    range_name = quote(f"'{sheet_title}'", safe="")
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.get(
            f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_name}",
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
            headers=_auth_header(token),
        )
        response.raise_for_status()
        return response.json().get("values", [])


def spreadsheet_id_from_url(value: str) -> str:
    raw = value.strip()
    if "/spreadsheets/d/" in raw:
        tail = raw.split("/spreadsheets/d/", 1)[1]
        return tail.split("/", 1)[0].strip()
    if raw and all(ch.isalnum() or ch in "-_" for ch in raw):
        return raw
    raise ValueError("Enter a Google Sheets URL or spreadsheet ID.")


def _auth_header(token: dict[str, Any]) -> dict[str, str]:
    access = token.get("access_token")
    if not access:
        raise RuntimeError("Missing Google access token.")
    return {"Authorization": f"Bearer {access}"}


def _token_valid(token: dict[str, Any]) -> bool:
    value = token.get("expires_at")
    if not value or not token.get("access_token"):
        return False
    try:
        return datetime.fromisoformat(str(value)) > datetime.now(timezone.utc) + timedelta(seconds=30)
    except ValueError:
        return False
