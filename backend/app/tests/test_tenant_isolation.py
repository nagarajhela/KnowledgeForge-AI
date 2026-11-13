import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.services.ingestion_service import IngestionService
from app.tests.conftest import register_user_and_org
from app.workers.tasks import ingest_document_task

SECRET_FILENAME = "org_a_acquisition_plan_2026.txt"
SECRET_CONTENT = "Project Obsidian acquisition budget is $48.5M closing Q4 2026."
SECRET_KEYWORD = "Obsidian"


def _assert_no_secret_leak(response_text: str, *, doc_id: str, kb_id: str) -> None:
    assert SECRET_FILENAME not in response_text
    assert SECRET_CONTENT not in response_text
    assert SECRET_KEYWORD not in response_text
    assert "48.5M" not in response_text
    assert "storage_path" not in response_text
    assert "download_url" not in response_text
    assert "organizations/" not in response_text
    assert "embedding" not in response_text
    assert "chunk_count" not in response_text
    assert doc_id not in response_text
    assert kb_id not in response_text


@pytest.mark.asyncio
async def test_adversarial_cross_tenant_document_isolation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Verifies strict tenant isolation when Organization A uploads a private document
    and Organization B attempts to:
      1. List the document
      2. Fetch document metadata
      3. Download its file
      4. Query its chunks through search
      5. Cite it in RAG chat
      6. Access it through direct UUID guessing (including API keys & chat/ingestion UUIDs)
      7. Process it through a Celery job (HTTP reprocess, ingestion trigger, and direct task call)
    """
    org_a = await register_user_and_org(client, email="owner_a@orga.com", org_name="Organization A")
    org_b = await register_user_and_org(client, email="owner_b@orgb.com", org_name="Organization B")

    # Organization A creates a KB, uploads a private document, and creates a chat session
    kb_a_resp = await client.post(
        "/api/v1/knowledge-bases",
        headers=org_a["headers"],
        json={"name": "Org A M&A Vault", "min_confidence_score": 0.1},
    )
    assert kb_a_resp.status_code == 201
    kb_a_id = kb_a_resp.json()["id"]

    upload_a = await client.post(
        f"/api/v1/knowledge-bases/{kb_a_id}/documents/upload",
        headers=org_a["headers"],
        files={"file": (SECRET_FILENAME, SECRET_CONTENT.encode("utf-8"), "text/plain")},
    )
    assert upload_a.status_code == 201
    doc_a_id = upload_a.json()["document"]["id"]
    job_a_id = upload_a.json()["ingestion_job_id"]
    assert upload_a.json()["document"]["chunk_count"] >= 1

    # Org A creates a chat session and gets an answer citing the private document
    sess_a = await client.post(
        "/api/v1/chat/sessions",
        headers=org_a["headers"],
        json={"title": "M&A Review", "knowledge_base_ids": [kb_a_id]},
    )
    assert sess_a.status_code == 201
    sess_a_id = sess_a.json()["id"]
    msg_a = await client.post(
        f"/api/v1/chat/sessions/{sess_a_id}/messages",
        headers=org_a["headers"],
        json={"question": "What is the Project Obsidian acquisition budget?"},
    )
    assert msg_a.status_code == 200
    msg_a_id = msg_a.json()["message_id"]
    assert len(msg_a.json()["citations"]) >= 1

    # Organization B also creates its own KB and API key so it has valid resources to probe with
    kb_b_resp = await client.post(
        "/api/v1/knowledge-bases",
        headers=org_b["headers"],
        json={"name": "Org B Public KB", "min_confidence_score": 0.1},
    )
    assert kb_b_resp.status_code == 201
    kb_b_id = kb_b_resp.json()["id"]

    key_b_resp = await client.post(
        "/api/v1/api-keys",
        headers=org_b["headers"],
        json={"name": "Org B Probe Key", "scopes": ["*"]},
    )
    assert key_b_resp.status_code == 201
    org_b_api_key = key_b_resp.json()["plaintext_key"]

    spoofed_headers = {
        "Authorization": f"Bearer {org_b['access_token']}",
        "X-Organization-ID": org_a["organization_id"],
    }

    # 1. Org B attempts to LIST the document (own org list, Org A's KB docs, and spoofed header)
    list_b_docs = await client.get("/api/v1/documents", headers=org_b["headers"])
    assert list_b_docs.status_code == 200
    assert list_b_docs.json()["total"] == 0
    assert list_b_docs.json()["items"] == []

    list_kb_a_docs = await client.get(
        f"/api/v1/knowledge-bases/{kb_a_id}/documents", headers=org_b["headers"]
    )
    assert list_kb_a_docs.status_code == 404
    _assert_no_secret_leak(list_kb_a_docs.text, doc_id=doc_a_id, kb_id=kb_a_id)

    spoof_list_docs = await client.get("/api/v1/documents", headers=spoofed_headers)
    assert spoof_list_docs.status_code == 403
    _assert_no_secret_leak(spoof_list_docs.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 2. Org B attempts to FETCH DOCUMENT METADATA
    for url in (
        f"/api/v1/documents/{doc_a_id}",
        f"/api/v1/documents/{doc_a_id}/status",
    ):
        r_own = await client.get(url, headers=org_b["headers"])
        assert r_own.status_code == 404
        _assert_no_secret_leak(r_own.text, doc_id=doc_a_id, kb_id=kb_a_id)

        r_spoof = await client.get(url, headers=spoofed_headers)
        assert r_spoof.status_code == 403
        _assert_no_secret_leak(r_spoof.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 3. Org B attempts to DOWNLOAD its file
    dl_own = await client.get(f"/api/v1/documents/{doc_a_id}/download-url", headers=org_b["headers"])
    assert dl_own.status_code == 404
    _assert_no_secret_leak(dl_own.text, doc_id=doc_a_id, kb_id=kb_a_id)

    dl_spoof = await client.get(f"/api/v1/documents/{doc_a_id}/download-url", headers=spoofed_headers)
    assert dl_spoof.status_code == 403
    _assert_no_secret_leak(dl_spoof.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 4. Org B attempts to QUERY ITS CHUNKS THROUGH SEARCH
    search_own = await client.post(
        "/api/v1/documents/search",
        headers=org_b["headers"],
        json={"query": "Project Obsidian acquisition budget", "top_k": 10},
    )
    assert search_own.status_code == 200
    assert search_own.json()["total"] == 0
    assert search_own.json()["results"] == []

    search_cross_kb = await client.post(
        "/api/v1/documents/search",
        headers=org_b["headers"],
        json={"query": "Obsidian", "knowledge_base_ids": [kb_a_id]},
    )
    assert search_cross_kb.status_code == 404
    _assert_no_secret_leak(search_cross_kb.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 5. Org B attempts to CITE IT IN RAG CHAT
    sess_b = await client.post(
        "/api/v1/chat/sessions",
        headers=org_b["headers"],
        json={"title": "Org B Chat", "knowledge_base_ids": [kb_b_id]},
    )
    assert sess_b.status_code == 201
    sess_b_id = sess_b.json()["id"]

    # 5a. Querying Org B's KB about Org A's secret returns insufficient_context with 0 citations
    ask_b = await client.post(
        f"/api/v1/chat/sessions/{sess_b_id}/messages",
        headers=org_b["headers"],
        json={"question": "What is the Project Obsidian acquisition budget?"},
    )
    assert ask_b.status_code == 200
    ask_b_body = ask_b.json()
    assert ask_b_body["insufficient_context"] is True
    assert ask_b_body["citations"] == []
    _assert_no_secret_leak(ask_b.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 5b. Attempting to override knowledge_base_ids with Org A's KB returns 404
    ask_override = await client.post(
        f"/api/v1/chat/sessions/{sess_b_id}/messages",
        headers=org_b["headers"],
        json={"question": "Obsidian budget?", "knowledge_base_ids": [kb_a_id]},
    )
    assert ask_override.status_code == 404
    _assert_no_secret_leak(ask_override.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 5c. Attempting to open a session against Org A's KB returns 404
    cross_sess = await client.post(
        "/api/v1/chat/sessions",
        headers=org_b["headers"],
        json={"title": "Hijack", "knowledge_base_ids": [kb_a_id]},
    )
    assert cross_sess.status_code == 404

    # 6. Org B attempts DIRECT UUID GUESSING across all resource endpoints & API key spoofing
    guessed_endpoints = [
        ("GET", f"/api/v1/knowledge-bases/{kb_a_id}"),
        ("PATCH", f"/api/v1/knowledge-bases/{kb_a_id}"),
        ("DELETE", f"/api/v1/knowledge-bases/{kb_a_id}"),
        ("DELETE", f"/api/v1/documents/{doc_a_id}"),
        ("GET", f"/api/v1/ingestion/jobs/{job_a_id}"),
        ("GET", f"/api/v1/chat/sessions/{sess_a_id}/messages"),
        ("GET", f"/api/v1/chat/sessions/{sess_a_id}/export"),
        ("POST", f"/api/v1/chat/messages/{msg_a_id}/feedback"),
    ]
    for method, path in guessed_endpoints:
        kwargs = {"headers": org_b["headers"]}
        if method == "PATCH":
            kwargs["json"] = {"name": "Hacked"}
        elif path.endswith("/feedback"):
            kwargs["json"] = {"rating": "down"}
        resp = await client.request(method, path, **kwargs)
        assert resp.status_code in (403, 404), f"{method} {path} returned {resp.status_code}"
        _assert_no_secret_leak(resp.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # Org B API key cannot spoof X-Organization-ID to access Org A
    api_key_spoof = await client.get(
        f"/api/v1/documents/{doc_a_id}",
        headers={"X-API-Key": org_b_api_key, "X-Organization-ID": org_a["organization_id"]},
    )
    assert api_key_spoof.status_code == 403
    _assert_no_secret_leak(api_key_spoof.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 7. Org B attempts to PROCESS IT THROUGH A CELERY JOB
    # 7a. HTTP reprocess endpoint
    reprocess_b = await client.post(
        f"/api/v1/documents/{doc_a_id}/reprocess", headers=org_b["headers"]
    )
    assert reprocess_b.status_code == 404
    _assert_no_secret_leak(reprocess_b.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 7b. HTTP ingestion trigger endpoint
    trigger_b = await client.post(
        "/api/v1/ingestion/jobs",
        headers=org_b["headers"],
        json={"document_id": doc_a_id},
    )
    assert trigger_b.status_code == 404
    _assert_no_secret_leak(trigger_b.text, doc_id=doc_a_id, kb_id=kb_a_id)

    # 7c. Direct IngestionService / Celery worker invocation with Org B's tenant ID + Org A's doc UUID
    with pytest.raises(NotFoundError):
        await IngestionService(db_session, uuid.UUID(org_b["organization_id"])).process_document(
            uuid.UUID(doc_a_id), job_id=uuid.UUID(job_a_id)
        )

    async def _direct_worker_call(organization_id: str, document_id: str, job_id: str) -> dict[str, str]:
        doc = await IngestionService(db_session, uuid.UUID(organization_id)).process_document(
            uuid.UUID(document_id), job_id=uuid.UUID(job_id)
        )
        return {"document_id": str(doc.id), "status": doc.processing_status.value}

    with patch("app.workers.tasks._run_ingestion", side_effect=_direct_worker_call):
        with pytest.raises(NotFoundError):
            ingest_document_task.apply(
                args=(org_b["organization_id"], doc_a_id, job_a_id),
                throw=True,
            )

    # Verify Org A's document remains completely intact and owned by Org A
    verify_a = await client.get(f"/api/v1/documents/{doc_a_id}", headers=org_a["headers"])
    assert verify_a.status_code == 200
    assert verify_a.json()["filename"] == SECRET_FILENAME
    assert verify_a.json()["processing_status"] == "completed"
