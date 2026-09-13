from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Iterable
from urllib.parse import quote, urlencode

import httpx

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class GoogleOutcomeUncertainError(httpx.TransportError):
    """A Google mutation returned success but its resulting object could not be verified.

    This subclasses TransportError deliberately: the queue already treats transport
    failures after Gmail mutations as uncertain and requires human verification
    instead of replaying them. A malformed 2xx response has the same safety model.
    """


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
    if token_is_valid(token):
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
        payload = response.json()
        email_address = payload.get("emailAddress") if isinstance(payload, dict) else None
        if not isinstance(email_address, str) or not email_address.strip():
            raise RuntimeError("Google Gmail profile response did not include an email address.")
        return email_address.strip()


def token_has_scope(token: dict[str, Any], scope: str) -> bool:
    scopes = str(token.get("scope") or "").split()
    return scope in scopes


def token_is_valid(token: dict[str, Any], *, margin_seconds: int = 30) -> bool:
    """Return whether an access token remains usable beyond the safety margin."""
    value = token.get("expires_at")
    if not value or not token.get("access_token"):
        return False
    try:
        expires_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > datetime.now(timezone.utc) + timedelta(seconds=max(0, margin_seconds))
    except (ValueError, TypeError, OverflowError):
        return False


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
            maintype, subtype = _mime_parts(content_type, filename)
            html_part.add_related(
                payload,
                maintype=maintype,
                subtype=subtype,
                cid=f"<{content_id}>",
                filename=filename,
                disposition="inline",
            )
    for filename, payload, content_type in attachments or []:
        maintype, subtype = _mime_parts(content_type, filename)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


async def create_draft(
    token: dict[str, Any],
    raw_message: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> str:
    return await _gmail_mutation(
        token,
        f"{GMAIL_BASE}/drafts",
        {"message": {"raw": raw_message}},
        operation="draft creation",
        http=http,
    )


async def send_message(
    token: dict[str, Any],
    raw_message: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> str:
    # Deliberately do not blindly retry this POST: after a timeout or connection
    # loss the server may already have accepted the message, and an automatic
    # replay could send a duplicate email.
    return await _gmail_mutation(
        token,
        f"{GMAIL_BASE}/messages/send",
        {"raw": raw_message},
        operation="send",
        http=http,
    )


async def _gmail_mutation(
    token: dict[str, Any],
    url: str,
    payload: dict[str, Any],
    *,
    operation: str,
    http: httpx.AsyncClient | None = None,
) -> str:
    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            url,
            headers={**_auth_header(token), "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        # A 2xx response means Google may already have committed the mutation. If
        # its body is malformed or the returned id is missing, replaying the POST
        # would risk a duplicate message/draft. Surface this as an explicitly
        # uncertain outcome so the queue can require human verification instead.
        try:
            decoded = response.json()
        except (ValueError, TypeError) as exc:
            raise GoogleOutcomeUncertainError(
                f"Gmail {operation} returned success but its response could not be verified."
            ) from exc
        remote_id = decoded.get("id") if isinstance(decoded, dict) else None
        if not isinstance(remote_id, str) or not remote_id.strip():
            raise GoogleOutcomeUncertainError(
                f"Gmail {operation} returned success without a verifiable remote id."
            )
        return remote_id.strip()
    finally:
        if owns_client:
            await client.aclose()


async def google_sheet_metadata(
    token: dict[str, Any],
    spreadsheet_id: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=60)
    try:
        response = await client.get(
            f"{SHEETS_BASE}/{spreadsheet_id}",
            params={
                "includeGridData": "false",
                "fields": "properties.title,sheets.properties(title,sheetType,gridProperties)",
            },
            headers=_auth_header(token),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Sheets returned invalid spreadsheet metadata.")
        return payload
    finally:
        if owns_client:
            await client.aclose()


async def google_sheet_values(
    token: dict[str, Any],
    spreadsheet_id: str,
    sheet_title: str,
    start_row: int | None = None,
    end_row: int | None = None,
    *,
    http: httpx.AsyncClient | None = None,
) -> list[list[Any]]:
    # A1 notation escapes apostrophes inside quoted sheet names by doubling them.
    # Without this, titles such as O'Brien produce an invalid range.
    a1_title = sheet_title.replace("'", "''")
    a1_range = f"'{a1_title}'"
    if start_row is not None or end_row is not None:
        if start_row is None or end_row is None or start_row < 1 or end_row < start_row:
            raise ValueError("Google Sheet row range is invalid.")
        a1_range += f"!{start_row}:{end_row}"
    range_name = quote(a1_range, safe="")
    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=60)
    try:
        response = await client.get(
            f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_name}",
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
            headers=_auth_header(token),
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Sheets returned an invalid values payload.")
        values = payload.get("values", [])
        if not isinstance(values, list):
            raise ValueError("Google Sheets returned an invalid values payload.")
        return values
    finally:
        if owns_client:
            await client.aclose()


def spreadsheet_id_from_url(value: str) -> str:
    raw = value.strip()
    if "/spreadsheets/d/" in raw:
        tail = raw.split("/spreadsheets/d/", 1)[1]
        spreadsheet_id = tail.split("/", 1)[0].strip()
        if spreadsheet_id and all(ch.isalnum() or ch in "-_" for ch in spreadsheet_id):
            return spreadsheet_id
        raise ValueError("The Google Sheets URL contains an invalid spreadsheet ID.")
    if raw and all(ch.isalnum() or ch in "-_" for ch in raw):
        return raw
    raise ValueError("Enter a Google Sheets URL or spreadsheet ID.")


def _auth_header(token: dict[str, Any]) -> dict[str, str]:
    access = token.get("access_token")
    if not access:
        raise RuntimeError("Missing Google access token.")
    return {"Authorization": f"Bearer {access}"}


def _mime_parts(content_type: str | None, filename: str) -> tuple[str, str]:
    guessed = str(content_type or "").strip().lower()
    if "/" not in guessed:
        guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    maintype, subtype = guessed.split("/", 1)
    if not maintype or not subtype or any(ch.isspace() for ch in maintype + subtype):
        return "application", "octet-stream"
    # Parameters belong in Content-Type parameters, not the subtype argument.
    subtype = subtype.split(";", 1)[0].strip()
    return (maintype, subtype) if subtype else ("application", "octet-stream")
