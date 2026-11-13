import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.providers.embeddings import get_embedding_provider
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.document import (
    DocumentChunkSearchResult,
    DocumentResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
    IngestionJobResponse,
    SignedDownloadResponse,
)
from app.services.document_service import DocumentService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get(
    "",
    response_model=PaginatedResponse[DocumentResponse],
    summary="List accessible documents across permitted knowledge bases in the active organization",
)
async def list_documents(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DocumentResponse]:
    docs, total = await DocumentService(db, tenant.organization_id).list_all_documents(
        user=tenant.user, role=tenant.role, offset=offset, limit=limit
    )
    return PaginatedResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/search",
    response_model=DocumentSearchResponse,
    summary="Hybrid vector + full-text chunk search scoped to active organization and permitted knowledge bases",
)
async def search_document_chunks(
    payload: DocumentSearchRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> DocumentSearchResponse:
    kb_service = KnowledgeBaseService(db, tenant.organization_id)
    if payload.knowledge_base_ids:
        kbs = await kb_service.validate_requested_kbs(
            payload.knowledge_base_ids, user=tenant.user, role=tenant.role
        )
    else:
        kbs, _ = await kb_service.list_kbs(user=tenant.user, role=tenant.role, offset=0, limit=100)

    if not kbs:
        return DocumentSearchResponse(results=[], total=0)

    primary_kb = kbs[0]
    embedder = get_embedding_provider(primary_kb.embedding_provider, model=primary_kb.embedding_model)
    query_vec = await embedder.embed_query(payload.query)
    chunks = await RetrievalService(db, tenant.organization_id).hybrid_search(
        query=payload.query,
        query_vector=query_vec,
        knowledge_base_ids=[kb.id for kb in kbs],
        top_k=payload.top_k,
        alpha=primary_kb.hybrid_alpha,
        rerank=primary_kb.rerank_enabled,
        metadata_filters=payload.metadata_filters,
    )
    results = [
        DocumentChunkSearchResult(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            knowledge_base_id=c.knowledge_base_id,
            document_name=c.document_name,
            content=c.content,
            page_number=c.page_number,
            source_url=c.source_url,
            relevance_score=c.relevance_score,
        )
        for c in chunks
    ]
    return DocumentSearchResponse(results=results, total=len(results))


@router.get("/{document_id}", response_model=DocumentResponse, summary="Get document metadata")
async def get_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    doc = await DocumentService(db, tenant.organization_id).get_document(
        document_id, user=tenant.user, role=tenant.role
    )
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/status", response_model=DocumentResponse, summary="Get document ingestion status")
async def get_document_status(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    doc = await DocumentService(db, tenant.organization_id).get_document(
        document_id, user=tenant.user, role=tenant.role
    )
    return DocumentResponse.model_validate(doc)


@router.post("/{document_id}/reprocess", response_model=IngestionJobResponse, summary="Re-run ingestion pipeline")
async def reprocess_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
) -> IngestionJobResponse:
    _, job = await DocumentService(db, tenant.organization_id).reprocess_document(
        document_id, user=tenant.user, role=tenant.role
    )
    return IngestionJobResponse.model_validate(job)


@router.get(
    "/{document_id}/download-url",
    response_model=SignedDownloadResponse,
    summary="Generate temporary signed S3/MinIO download URL",
)
async def get_signed_download_url(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> SignedDownloadResponse:
    url = await DocumentService(db, tenant.organization_id).get_download_url(
        document_id, user=tenant.user, role=tenant.role
    )
    return SignedDownloadResponse(
        document_id=document_id,
        download_url=url,
        expires_in_seconds=900,
    )


@router.delete("/{document_id}", response_model=MessageResponse, summary="Archive and soft-delete document")
async def delete_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.DOCUMENT_DELETE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await DocumentService(db, tenant.organization_id).delete_document(
        document_id, tenant.user, role=tenant.role
    )
    return MessageResponse(message="Document deleted")
