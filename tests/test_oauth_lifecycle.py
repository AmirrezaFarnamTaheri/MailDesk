from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from mailmerge_app.oauth_client import (
    GOOGLE_OAUTH,
    OAuthProtocolError,
    new_authorization_request,
    refresh_access_token,
    revoke_access,
    token_health,
)


def test_authorization_request_uses_pkce_state_and_login_hint():
    url, session = new_authorization_request(
        GOOGLE_OAUTH,
        {"client_id": "desktop-client", "client_secret": "not-confidential"},
        "http://127.0.0.1:8765/oauth/google/callback",
        ["scope-a", "scope-b"],
        login_hint="person@example.com",
        prompt="consent",
    )
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [session["state"]]
    assert query["login_hint"] == ["person@example.com"]
    assert query["prompt"] == ["consent"]
    assert len(session["verifier"]) > 40


def test_refresh_accepts_rotated_refresh_token_and_preserves_scope():
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            body = parse_qs(request.content.decode())
            assert body["refresh_token"] == ["refresh-old"]
            return httpx.Response(
                200,
                json={"access_token": "access-new", "expires_in": 3600, "refresh_token": "refresh-rotated"},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            return await refresh_access_token(
                GOOGLE_OAUTH,
                {
                    "access_token": "access-old",
                    "refresh_token": "refresh-old",
                    "scope": "scope-a scope-b",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                },
                {"client_id": "desktop-client", "client_secret": "secret"},
                http=http,
            )

    token = asyncio.run(run())
    assert token["access_token"] == "access-new"
    assert token["refresh_token"] == "refresh-rotated"
    assert token["scope"] == "scope-a scope-b"
    assert token_health(token)["refresh_available"] is True


def test_refresh_invalid_grant_requests_reconnect_without_leaking_tokens():
    async def run():
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            await refresh_access_token(
                GOOGLE_OAUTH,
                {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_at": "2000-01-01T00:00:00+00:00"},
                {"client_id": "desktop-client", "client_secret": "client-secret"},
                http=http,
            )

    with pytest.raises(OAuthProtocolError) as exc:
        asyncio.run(run())
    assert exc.value.code == "invalid_grant"
    message = str(exc.value)
    assert "Reconnect" in message
    assert "access-secret" not in message
    assert "refresh-secret" not in message
    assert "client-secret" not in message


def test_explicit_revocation_prefers_refresh_token():
    seen = {}

    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(parse_qs(request.content.decode()))
            return httpx.Response(200, json={})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            await revoke_access(
                GOOGLE_OAUTH,
                {"access_token": "access-token", "refresh_token": "refresh-token"},
                http=http,
            )

    asyncio.run(run())
    assert seen["token"] == ["refresh-token"]


def test_token_response_rejects_non_bearer_token_type():
    async def run():
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "access", "token_type": "MAC", "expires_in": 3600})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            await refresh_access_token(
                GOOGLE_OAUTH,
                {"refresh_token": "refresh", "expires_at": "2000-01-01T00:00:00+00:00"},
                {"client_id": "desktop-client"},
                http=http,
            )

    with pytest.raises(OAuthProtocolError) as exc:
        asyncio.run(run())
    assert exc.value.code == "invalid_response"
    assert "token type" in str(exc.value)


def test_token_response_rejects_non_positive_expiry():
    async def run():
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "access", "token_type": "Bearer", "expires_in": 0})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            await refresh_access_token(
                GOOGLE_OAUTH,
                {"refresh_token": "refresh", "expires_at": "2000-01-01T00:00:00+00:00"},
                {"client_id": "desktop-client"},
                http=http,
            )

    with pytest.raises(OAuthProtocolError) as exc:
        asyncio.run(run())
    assert exc.value.code == "invalid_response"
    assert "expired access token" in str(exc.value)
