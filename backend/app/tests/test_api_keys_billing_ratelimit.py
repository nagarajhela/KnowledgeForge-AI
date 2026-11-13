import pytest
from httpx import AsyncClient

from app.core.rate_limit import rate_limiter
from app.tests.conftest import register_user_and_org


@pytest.mark.asyncio
async def test_api_key_auth_billing_quotas_analytics_and_webhook_idempotency(
    client: AsyncClient,
) -> None:
    tenant = await register_user_and_org(client, email="ops@acme.com", org_name="Ops Co")

    # 1) Create API Key (shown once)
    key_resp = await client.post(
        "/api/v1/api-keys",
        headers=tenant["headers"],
        json={"name": "CI Pipeline Key", "scopes": ["kb:read", "kb:write", "analytics:read"]},
    )
    assert key_resp.status_code == 201
    plaintext_key = key_resp.json()["plaintext_key"]
    key_id = key_resp.json()["id"]
    assert plaintext_key.startswith("kf_live_")

    # List keys never exposes plaintext_key
    list_keys = await client.get("/api/v1/api-keys", headers=tenant["headers"])
    assert list_keys.status_code == 200
    assert "plaintext_key" not in list_keys.json()[0]

    # Authenticate using X-API-Key
    kb_by_key = await client.post(
        "/api/v1/knowledge-bases",
        headers={"X-API-Key": plaintext_key},
        json={"name": "API Created KB"},
    )
    assert kb_by_key.status_code == 201

    # Free plan allows 3 knowledge bases -> create 2 more, then 4th fails with 402 QuotaExceeded
    for i in range(2):
        r = await client.post(
            "/api/v1/knowledge-bases",
            headers=tenant["headers"],
            json={"name": f"KB {i + 2}"},
        )
        assert r.status_code == 201

    quota_exceeded = await client.post(
        "/api/v1/knowledge-bases",
        headers=tenant["headers"],
        json={"name": "KB 4 Over Quota"},
    )
    assert quota_exceeded.status_code == 402
    assert quota_exceeded.json()["error"]["code"] == "quota_exceeded"

    # Upgrade plan to Pro -> 4th KB now succeeds
    upgrade = await client.post(
        "/api/v1/billing/plan",
        headers=tenant["headers"],
        json={"plan_tier": "pro"},
    )
    assert upgrade.status_code == 200
    assert upgrade.json()["plan_tier"] == "pro"

    kb4 = await client.post(
        "/api/v1/knowledge-bases",
        headers=tenant["headers"],
        json={"name": "KB 4 After Upgrade"},
    )
    assert kb4.status_code == 201

    # Analytics overview reflects created resources
    analytics = await client.get("/api/v1/analytics/overview", headers=tenant["headers"])
    assert analytics.status_code == 200
    assert len(analytics.json()["api_key_usage"]) == 1

    # Revoke API key -> subsequent API key auth fails with 401
    revoke = await client.delete(f"/api/v1/api-keys/{key_id}", headers=tenant["headers"])
    assert revoke.status_code == 200
    revoked_attempt = await client.get("/api/v1/knowledge-bases", headers={"X-API-Key": plaintext_key})
    assert revoked_attempt.status_code == 401

    # Stripe webhook idempotency
    evt = {"id": "evt_12345", "type": "invoice.paid", "data": {"object": {"metadata": {}}}}
    wh1 = await client.post("/api/v1/webhooks/stripe", json=evt)
    assert wh1.status_code == 200
    assert wh1.json()["duplicate"] is False

    wh2 = await client.post("/api/v1/webhooks/stripe", json=evt)
    assert wh2.status_code == 200
    assert wh2.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_rate_limiter_enforces_threshold() -> None:
    rate_limiter._local_buckets.clear()
    await rate_limiter.check_rate_limit("unit:test", limit=2, window_seconds=60)
    await rate_limiter.check_rate_limit("unit:test", limit=2, window_seconds=60)
    with pytest.raises(Exception) as exc_info:
        await rate_limiter.check_rate_limit("unit:test", limit=2, window_seconds=60)
    assert "Rate limit" in str(exc_info.value)
