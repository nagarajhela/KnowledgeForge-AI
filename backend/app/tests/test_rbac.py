import pytest
from httpx import AsyncClient

from app.tests.conftest import register_user_and_org


@pytest.mark.asyncio
async def test_rbac_viewer_cannot_create_kb_or_upload(client: AsyncClient) -> None:
    owner = await register_user_and_org(client, email="owner@acme.com", org_name="Acme Inc")
    viewer = await register_user_and_org(client, email="viewer@acme.com", org_name="Personal")

    # Owner invites viewer as VIEWER
    invite_resp = await client.post(
        f"/api/v1/organizations/{owner['organization_id']}/invite",
        headers=owner["headers"],
        json={"email": "viewer@acme.com", "role": "viewer"},
    )
    assert invite_resp.status_code == 201
    invite_token = invite_resp.json()["invite_token"]

    # Viewer accepts invitation
    accept = await client.post(
        "/api/v1/invitations/accept",
        headers={"Authorization": f"Bearer {viewer['access_token']}"},
        json={"token": invite_token},
    )
    assert accept.status_code == 200

    viewer_org_headers = {
        "Authorization": f"Bearer {viewer['access_token']}",
        "X-Organization-ID": owner["organization_id"],
    }

    # Viewer cannot create a knowledge base (403)
    kb_create = await client.post(
        "/api/v1/knowledge-bases",
        headers=viewer_org_headers,
        json={"name": "Unauthorized KB"},
    )
    assert kb_create.status_code == 403

    # Owner creates KB, viewer CAN list/read it
    owner_kb = await client.post(
        "/api/v1/knowledge-bases",
        headers=owner["headers"],
        json={"name": "Company Handbook"},
    )
    assert owner_kb.status_code == 201
    kb_id = owner_kb.json()["id"]

    kb_list = await client.get("/api/v1/knowledge-bases", headers=viewer_org_headers)
    assert kb_list.status_code == 200
    assert kb_list.json()["total"] == 1

    # Viewer cannot upload documents (403)
    upload = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=viewer_org_headers,
        files={"file": ("policy.txt", b"Secret content", "text/plain")},
    )
    assert upload.status_code == 403

    # Owner promotes viewer to billing_manager -> billing allowed, KB read denied
    role_upd = await client.patch(
        f"/api/v1/members/{viewer['user']['id']}/role",
        headers=owner["headers"],
        json={"role": "billing_manager"},
    )
    assert role_upd.status_code == 200

    billing_resp = await client.get("/api/v1/billing", headers=viewer_org_headers)
    assert billing_resp.status_code == 200
    kb_denied = await client.get("/api/v1/knowledge-bases", headers=viewer_org_headers)
    assert kb_denied.status_code == 403
