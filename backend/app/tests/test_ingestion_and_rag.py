import uuid

import pytest
from httpx import AsyncClient

from app.providers.extractors.base import ExtractedDocument, ExtractedPage
from app.services.chunking_service import ChunkingService
from app.tests.conftest import register_user_and_org


@pytest.mark.asyncio
async def test_document_upload_dedup_and_rag_chat_with_citations(client: AsyncClient) -> None:
    tenant = await register_user_and_org(client, email="rag@acme.com", org_name="RAG Corp")

    kb_resp = await client.post(
        "/api/v1/knowledge-bases",
        headers=tenant["headers"],
        json={
            "name": "HR Policies",
            "chunk_size": 256,
            "chunk_overlap": 32,
            "min_confidence_score": 0.1,
        },
    )
    assert kb_resp.status_code == 201
    kb_id = kb_resp.json()["id"]

    content = (
        b"Employee Handbook 2026\n\n"
        b"Full-time employees receive 20 paid vacation days per calendar year. "
        b"Unused annual leave up to 5 days can roll over into Q1."
    )
    up1 = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers={**tenant["headers"], "Idempotency-Key": "upload-key-1"},
        files={"file": ("Employee Handbook 2026.txt", content, "text/plain")},
    )
    assert up1.status_code == 201
    body1 = up1.json()
    assert body1["deduplicated"] is False
    assert body1["document"]["processing_status"] == "completed"
    assert body1["document"]["chunk_count"] >= 1
    doc_id = body1["document"]["id"]

    # Duplicate upload (same SHA-256 checksum) is deduplicated
    up2 = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=tenant["headers"],
        files={"file": ("Handbook Copy.txt", content, "text/plain")},
    )
    assert up2.status_code == 201
    assert up2.json()["deduplicated"] is True
    assert up2.json()["document"]["id"] == doc_id

    # Create chat session and ask question
    sess_resp = await client.post(
        "/api/v1/chat/sessions",
        headers=tenant["headers"],
        json={"title": "Leave Policy Q&A", "knowledge_base_ids": [kb_id]},
    )
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["id"]

    ask_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=tenant["headers"],
        json={"question": "How many paid vacation days do full-time employees receive?"},
    )
    assert ask_resp.status_code == 200
    answer_data = ask_resp.json()
    assert "20 paid vacation days" in answer_data["answer"]
    assert len(answer_data["citations"]) >= 1
    assert answer_data["citations"][0]["document_id"] == doc_id
    assert answer_data["citations"][0]["document_name"] == "Employee Handbook 2026.txt"
    assert answer_data["confidence_score"] > 0

    # Feedback & Markdown export
    msg_id = answer_data["message_id"]
    fb = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        headers=tenant["headers"],
        json={"rating": "up", "comment": "Accurate citation"},
    )
    assert fb.status_code == 201

    export = await client.get(
        f"/api/v1/chat/sessions/{session_id}/export",
        headers=tenant["headers"],
    )
    assert export.status_code == 200
    assert "Employee Handbook 2026.txt" in export.text

    # SSE Streaming check
    stream_resp = await client.get(
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=tenant["headers"],
        params={"question": "Can unused annual leave roll over?"},
    )
    assert stream_resp.status_code == 200
    assert "event: token" in stream_resp.text
    assert "event: done" in stream_resp.text


def test_chunking_service_respects_overlap() -> None:
    chunker = ChunkingService()
    long_text = " ".join(f"word{i}" for i in range(400))
    extracted = ExtractedDocument(pages=[ExtractedPage(text=long_text, page_number=1)], page_count=1)
    chunks = chunker.chunk_document(extracted, chunk_size=120, chunk_overlap=20)
    assert len(chunks) >= 3
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1
