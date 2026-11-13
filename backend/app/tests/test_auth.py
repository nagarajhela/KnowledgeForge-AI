import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.tests.conftest import register_user_and_org


@pytest.mark.asyncio
async def test_register_login_refresh_rotation_and_reuse_detection(client: AsyncClient) -> None:
    ctx = await register_user_and_org(client, email="alice@example.com", org_name="Alice Org")

    # Login
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "StrongPass123!", "device_name": "pytest"},
    )
    assert login.status_code == 200
    old_refresh = login.json()["refresh_token"]

    # Rotate refresh token once -> succeeds
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    new_refresh = rotated.json()["refresh_token"]
    assert new_refresh != old_refresh

    # Reuse old rotated refresh token -> triggers family revocation (401)
    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "refresh_token_reused"

    # Subsequent attempt with new_refresh in revoked family also fails
    revoked_new = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert revoked_new.status_code == 401

    # Profile read works with valid access token
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {ctx['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_failed_login_lockout(client: AsyncClient) -> None:
    await register_user_and_org(client, email="lockout@example.com", org_name="Lockout Org")

    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        bad = await client.post(
            "/api/v1/auth/login",
            json={"email": "lockout@example.com", "password": "WrongPassword!"},
        )
        assert bad.status_code == 401

    locked = await client.post(
        "/api/v1/auth/login",
        json={"email": "lockout@example.com", "password": "StrongPass123!"},
    )
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "rate_limit_exceeded"
