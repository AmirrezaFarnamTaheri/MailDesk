from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    """Minimal OAuth 2.0 provider description used by MailDesk's local client flow."""

    key: str
    display_name: str
    authorization_url: str
    token_url: str
    revoke_url: str = ""


GOOGLE_OAUTH = OAuthProvider(
    key="google",
    display_name="Google",
    authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    revoke_url="https://oauth2.googleapis.com/revoke",
)


class OAuthProtocolError(RuntimeError):
    """Safe, user-facing OAuth failure without leaking token endpoint payloads."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def parse_installed_client(document: bytes, *, provider_name: str = "Google") -> dict[str, str]:
    """Parse a desktop/installed-app OAuth client JSON document.

    MailDesk intentionally rejects web-application clients because their redirect
    URI/security model is different from a local desktop application.
    """

    try:
        parsed = json.loads(document.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The OAuth client JSON is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("The OAuth client JSON must contain an object.")
    if "web" in parsed:
        raise ValueError(f"Use a {provider_name} OAuth client of type Desktop app, not Web application.")
    installed = parsed.get("installed")
    if not isinstance(installed, dict) or not installed.get("client_id"):
        raise ValueError(f"The file is not a valid {provider_name} Desktop app OAuth client JSON.")
    # Google's downloaded installed-app JSON currently includes a client_secret.
    # Keep it optional here so public native clients can still use PKCE safely.
    client = {"client_id": str(installed["client_id"]).strip()}
    client_secret = str(installed.get("client_secret") or "").strip()
    if client_secret:
        client["client_secret"] = client_secret
    return client


def new_authorization_request(
    provider: OAuthProvider,
    client: dict[str, str],
    redirect_uri: str,
    scopes: Iterable[str],
    *,
    login_hint: str = "",
    prompt: str = "consent select_account",
) -> tuple[str, dict[str, str]]:
    """Create a one-time authorization-code + PKCE request."""

    client_id = str(client.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("OAuth client ID is missing.")
    scope_list = [str(scope).strip() for scope in scopes if str(scope).strip()]
    if not scope_list:
        raise ValueError("At least one OAuth scope is required.")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scope_list),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if prompt.strip():
        params["prompt"] = prompt.strip()
    if login_hint.strip():
        params["login_hint"] = login_hint.strip()

    return f"{provider.authorization_url}?{urlencode(params)}", {
        "provider": provider.key,
        "state": state,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "requested_scopes": " ".join(scope_list),
        "login_hint": login_hint.strip(),
    }


async def exchange_authorization_code(
    provider: OAuthProvider,
    client: dict[str, str],
    code: str,
    verifier: str,
    redirect_uri: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    payload = {
        "client_id": client.get("client_id", ""),
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if client.get("client_secret"):
        payload["client_secret"] = client["client_secret"]
    response = await _post_form(provider, payload, action="authorization", http=http)
    return _normalize_token_response(response, previous=None)


async def refresh_access_token(
    provider: OAuthProvider,
    token: dict[str, Any],
    client: dict[str, str],
    *,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    if token_is_valid(token):
        return token
    refresh = str(token.get("refresh_token") or "").strip()
    if not refresh:
        raise OAuthProtocolError(f"This {provider.display_name} account has no refresh token. Reconnect the account.", code="missing_refresh_token")
    payload = {
        "client_id": client.get("client_id", ""),
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }
    if client.get("client_secret"):
        payload["client_secret"] = client["client_secret"]
    response = await _post_form(provider, payload, action="token refresh", http=http)
    return _normalize_token_response(response, previous=token)


async def revoke_access(
    provider: OAuthProvider,
    token: dict[str, Any],
    *,
    http: httpx.AsyncClient | None = None,
) -> None:
    """Revoke the strongest available credential for an explicit user request."""

    if not provider.revoke_url:
        raise OAuthProtocolError(f"{provider.display_name} does not expose a configured revocation endpoint.", code="revocation_unavailable")
    credential = str(token.get("refresh_token") or token.get("access_token") or "").strip()
    if not credential:
        return

    async def _send(client_http: httpx.AsyncClient) -> None:
        try:
            response = await client_http.post(provider.revoke_url, data={"token": credential}, timeout=30)
        except httpx.HTTPError as exc:
            raise OAuthProtocolError(f"Could not contact {provider.display_name} to revoke access.", code="network_error") from exc
        if response.status_code not in {200, 400}:
            raise OAuthProtocolError(f"{provider.display_name} did not accept the revocation request.", code="revocation_failed")
        if response.status_code == 400:
            # An already-invalid token is effectively revoked; do not block local cleanup.
            return

    if http is None:
        async with httpx.AsyncClient(timeout=30) as owned_http:
            await _send(owned_http)
    else:
        await _send(http)


def token_scopes(token: dict[str, Any]) -> set[str]:
    raw = token.get("scope") or ""
    if isinstance(raw, (list, tuple, set)):
        return {str(scope).strip() for scope in raw if str(scope).strip()}
    return {part for part in str(raw).replace(",", " ").split() if part}


def token_has_scope(token: dict[str, Any], scope: str) -> bool:
    return scope in token_scopes(token)


def token_is_valid(token: dict[str, Any], *, margin_seconds: int = 30) -> bool:
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


def token_health(token: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret token metadata suitable for the local UI/API."""

    scopes = token_scopes(token)
    expires_at = str(token.get("expires_at") or "")
    return {
        "scopes": sorted(scopes),
        "expires_at": expires_at,
        "access_valid": token_is_valid(token),
        "refresh_available": bool(token.get("refresh_token")),
    }


async def _post_form(
    provider: OAuthProvider,
    data: dict[str, Any],
    *,
    action: str,
    http: httpx.AsyncClient | None,
) -> dict[str, Any]:
    async def _send(client_http: httpx.AsyncClient) -> dict[str, Any]:
        try:
            response = await client_http.post(provider.token_url, data=data, timeout=30)
        except httpx.HTTPError as exc:
            raise OAuthProtocolError(f"Could not contact {provider.display_name} during {action}.", code="network_error") from exc

        try:
            decoded = response.json()
        except (ValueError, TypeError):
            decoded = None
        if response.is_error:
            code = str(decoded.get("error") or "") if isinstance(decoded, dict) else ""
            description = str(decoded.get("error_description") or "") if isinstance(decoded, dict) else ""
            if code == "invalid_grant":
                raise OAuthProtocolError(
                    f"{provider.display_name} authorization is expired, revoked, or no longer valid. Reconnect the account.",
                    code=code,
                )
            if code == "invalid_client":
                raise OAuthProtocolError(
                    f"{provider.display_name} rejected the saved OAuth client. Replace the Desktop app OAuth client JSON and try again.",
                    code=code,
                )
            if code == "invalid_scope":
                raise OAuthProtocolError(
                    f"{provider.display_name} rejected one of the requested permissions. Update the OAuth setup and reconnect.",
                    code=code,
                )
            detail = description.strip() or code.strip() or f"HTTP {response.status_code}"
            # Provider descriptions are normally safe text; cap them so an upstream
            # HTML/error dump cannot spill into the desktop UI or logs.
            detail = detail.replace("\r", " ").replace("\n", " ")[:240]
            raise OAuthProtocolError(f"{provider.display_name} {action} failed: {detail}", code=code)
        if not isinstance(decoded, dict):
            raise OAuthProtocolError(f"{provider.display_name} {action} returned an invalid response.", code="invalid_response")
        return decoded

    if http is None:
        async with httpx.AsyncClient(timeout=30) as owned_http:
            return await _send(owned_http)
    return await _send(http)


def _normalize_token_response(response: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    access_token = str(response.get("access_token") or "").strip()
    if not access_token:
        raise OAuthProtocolError("OAuth token response did not include an access token.", code="invalid_response")
    token_type = str(response.get("token_type") or "Bearer").strip()
    if token_type.casefold() != "bearer":
        raise OAuthProtocolError("OAuth token response used an unsupported token type.", code="invalid_response")
    try:
        lifetime = int(response.get("expires_in", 3600))
    except (TypeError, ValueError) as exc:
        raise OAuthProtocolError("OAuth token response included an invalid expiry.", code="invalid_response") from exc
    if lifetime <= 0:
        raise OAuthProtocolError("OAuth token response included an expired access token.", code="invalid_response")

    merged = dict(previous or {})
    merged.update(response)
    merged["token_type"] = "Bearer"
    # Some providers rotate refresh tokens. Keep the new token if one was
    # returned; otherwise preserve the existing refresh token.
    if not response.get("refresh_token") and previous and previous.get("refresh_token"):
        merged["refresh_token"] = previous["refresh_token"]
    if not response.get("scope") and previous and previous.get("scope"):
        merged["scope"] = previous["scope"]
    merged["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=max(0, lifetime - 60))).isoformat()
    return merged
