import hashlib
import hmac
import time
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.exceptions import AppError
from app.providers.extractors.implementations import fetch_and_extract_url
from app.tests.conftest import register_user_and_org


@pytest.mark.asyncio
async def test_ssrf_redirect_to_private_ip_is_blocked() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://public.example.com/start":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8080/admin"})
        return httpx.Response(200, text="internal secret")

    mock_transport = httpx.MockTransport(_handler)
    original_async_client = httpx.AsyncClient

    def _patched_client(*args, **kwargs):
        kwargs["transport"] = mock_transport
        return original_async_client(*args, **kwargs)

    with (
        patch("app.providers.extractors.implementations.socket.getaddrinfo") as mock_dns,
        patch("app.providers.extractors.implementations.httpx.AsyncClient", side_effect=_patched_client),
    ):
        mock_dns.side_effect = lambda host, *_: (
            [(2, 1, 6, "", ("93.184.216.34", 0))]
            if host == "public.example.com"
            else [(2, 1, 6, "", ("127.0.0.1", 0))]
        )
        with pytest.raises(AppError, match="restricted internal network"):
            await fetch_and_extract_url("https://public.example.com/start")


@pytest.mark.asyncio
async def test_upload_rejects_magic_byte_spoofing(client: AsyncClient) -> None:
    org = await register_user_and_org(client, email="sec_upload@acme.com", org_name="Sec Upload Org")
    kb = await client.post(
        "/api/v1/knowledge-bases",
        headers=org["headers"],
        json={"name": "Sec KB"},
    )
    assert kb.status_code == 201
    kb_id = kb.json()["id"]

    spoofed_pdf = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=org["headers"],
        files={"file": ("malware.pdf", b"\x7fELF\x02\x01\x01\x00", "application/pdf")},
    )
    assert spoofed_pdf.status_code == 400


@pytest.mark.asyncio
async def test_oauth_callback_blocks_mock_fallback_in_production(client: AsyncClient) -> None:
    auth_resp = await client.get("/api/v1/auth/oauth/google/authorize")
    assert auth_resp.status_code == 200
    state = auth_resp.json()["state"]

    # Works in test environment with signed state
    ok_resp = await client.post(
        "/api/v1/auth/oauth/google/callback",
        params={"code": "dev-code-1234", "state": state, "email": "sso@acme.com"},
    )
    assert ok_resp.status_code == 200
    assert "access_token" in ok_resp.json()

    # Rejects unconfigured provider in production
    original_env = settings.APP_ENV
    try:
        settings.APP_ENV = "production"
        prod_resp = await client.post(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "attacker-code", "state": state, "email": "admin@acme.com"},
        )
        assert prod_resp.status_code == 401
    finally:
        settings.APP_ENV = original_env


@pytest.mark.asyncio
async def test_stripe_webhook_hmac_signature_verification(client: AsyncClient) -> None:
    original_secret = settings.STRIPE_WEBHOOK_SECRET
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_secret_123"
    try:
        payload = b'{"id": "evt_hmac_1", "type": "invoice.paid", "data": {}}'
        ts = str(int(time.time()))
        signed = f"{ts}.".encode("utf-8") + payload
        sig = hmac.new(b"whsec_test_secret_123", signed, hashlib.sha256).hexdigest()

        bad_resp = await client.post(
            "/api/v1/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": f"t={ts},v1=deadbeef"},
        )
        assert bad_resp.status_code == 401

        good_resp = await client.post(
            "/api/v1/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": f"t={ts},v1={sig}"},
        )
        assert good_resp.status_code == 200
        assert good_resp.json()["duplicate"] is False
    finally:
        settings.STRIPE_WEBHOOK_SECRET = original_secret


@pytest.mark.asyncio
async def test_provider_config_encryption_isolation_and_sse_streaming(client: AsyncClient) -> None:
    org_a = await register_user_and_org(client, email="prov_a@orga.com", org_name="Provider Org A")
    org_b = await register_user_and_org(client, email="prov_b@orgb.com", org_name="Provider Org B")

    upsert = await client.put(
        "/api/v1/provider-configs",
        headers=org_a["headers"],
        json={
            "provider_name": "openai",
            "api_key": "sk-secret-org-a-key-999",
            "default_model": "gpt-4o-mini",
        },
    )
    assert upsert.status_code == 200
    assert "sk-secret-org-a-key-999" not in upsert.text

    list_a = await client.get("/api/v1/provider-configs", headers=org_a["headers"])
    assert list_a.status_code == 200
    assert len(list_a.json()) == 1
    assert "sk-secret-org-a-key-999" not in list_a.text

    list_b = await client.get("/api/v1/provider-configs", headers=org_b["headers"])
    assert list_b.status_code == 200
    assert list_b.json() == []

    # Create KB, upload doc, and verify SSE stream commits assistant message cleanly
    kb = await client.post(
        "/api/v1/knowledge-bases",
        headers=org_a["headers"],
        json={"name": "SSE KB", "min_confidence_score": 0.1},
    )
    kb_id = kb.json()["id"]
    up = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=org_a["headers"],
        files={"file": ("sse_guide.txt", b"KnowledgeForge SSE streaming commits post-stream.", "text/plain")},
    )
    assert up.status_code == 201

    sess = await client.post(
        "/api/v1/chat/sessions",
        headers=org_a["headers"],
        json={"title": "SSE Session", "knowledge_base_ids": [kb_id]},
    )
    sess_id = sess.json()["id"]

    stream_resp = await client.get(
        f"/api/v1/chat/sessions/{sess_id}/stream",
        headers=org_a["headers"],
        params={"question": "What does KnowledgeForge SSE streaming do?"},
    )
    assert stream_resp.status_code == 200
    assert "event: token" in stream_resp.text
    assert "event: done" in stream_resp.text

    msgs = await client.get(f"/api/v1/chat/sessions/{sess_id}/messages", headers=org_a["headers"])
    assert msgs.status_code == 200
    assert len(msgs.json()) == 2
