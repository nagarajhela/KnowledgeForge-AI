import uuid

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.document import DocumentResponse, DocumentUploadResponse, DocumentURLIngestRequest
from app.schemas.knowledge_base import (
    KnowledgeBaseAccessAssignRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
)
from app.services.document_service import DocumentService
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])


@router.get(
    "",
    response_model=PaginatedResponse[KnowledgeBaseResponse],
    summary="List accessible knowledge bases in the active organization",
)
async def list_knowledge_bases(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[KnowledgeBaseResponse]:
    items, total = await KnowledgeBaseService(db, tenant.organization_id).list_kbs(
        user=tenant.user, role=tenant.role, offset=offset, limit=limit
    )
    return PaginatedResponse(
        items=[KnowledgeBaseResponse.model_validate(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new knowledge base",
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb = await KnowledgeBaseService(db, tenant.organization_id).create_kb(tenant.user, payload)
    return KnowledgeBaseResponse.model_validate(kb)


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    summary="Get knowledge base details",
)
async def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb = await KnowledgeBaseService(db, tenant.organization_id).get_kb_for_user(
        knowledge_base_id, user=tenant.user, role=tenant.role
    )
    return KnowledgeBaseResponse.model_validate(kb)


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    summary="Update knowledge base, AI model, or retrieval settings",
)
async def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseUpdateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb = await KnowledgeBaseService(db, tenant.organization_id).update_kb(
        knowledge_base_id, tenant.user, tenant.role, payload
    )
    return KnowledgeBaseResponse.model_validate(kb)


@router.delete(
    "/{knowledge_base_id}",
    response_model=MessageResponse,
    summary="Archive or soft-delete a knowledge base",
)
async def delete_knowledge_base(
    knowledge_base_id: uuid.UUID,
    archive_only: bool = True,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_DELETE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await KnowledgeBaseService(db, tenant.organization_id).delete_or_archive_kb(
        knowledge_base_id, tenant.user, tenant.role, archive_only=archive_only
    )
    return MessageResponse(message="Knowledge base archived" if archive_only else "Knowledge base deleted")


@router.put(
    "/{knowledge_base_id}/access",
    response_model=KnowledgeBaseResponse,
    summary="Assign user/team access scope to a knowledge base",
)
async def assign_kb_access(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseAccessAssignRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb = await KnowledgeBaseService(db, tenant.organization_id).assign_access(
        knowledge_base_id, tenant.user, tenant.role, payload
    )
    return KnowledgeBaseResponse.model_validate(kb)


@router.get(
    "/{knowledge_base_id}/documents",
    response_model=PaginatedResponse[DocumentResponse],
    summary="List documents in a knowledge base",
)
async def list_kb_documents(
    knowledge_base_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DocumentResponse]:
    docs, total = await DocumentService(db, tenant.organization_id).list_documents(
        knowledge_base_id, user=tenant.user, role=tenant.role, offset=offset, limit=limit
    )
    return PaginatedResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/{knowledge_base_id}/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document to a knowledge base and queue ingestion",
)
async def upload_document(
    knowledge_base_id: uuid.UUID,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant: TenantContext = Depends(require_permissions(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    raw_bytes = await file.read()
    doc, job, deduplicated = await DocumentService(db, tenant.organization_id).upload_file(
        kb_id=knowledge_base_id,
        actor=tenant.user,
        role=tenant.role,
        filename=file.filename or "upload.txt",
        content_type=file.content_type or "application/octet-stream",
        data=raw_bytes,
        idempotency_key=idempotency_key,
    )
    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(doc),
        ingestion_job_id=job.id,
        deduplicated=deduplicated,
    )


@router.post(
    "/{knowledge_base_id}/documents/url",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a public website URL for extraction and ingestion",
)
async def ingest_url(
    knowledge_base_id: uuid.UUID,
    payload: DocumentURLIngestRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    doc, job, deduplicated = await DocumentService(db, tenant.organization_id).ingest_url(
        kb_id=knowledge_base_id,
        actor=tenant.user,
        role=tenant.role,
        payload=payload,
    )
    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(doc),
        ingestion_job_id=job.id,
        deduplicated=deduplicated,
    )
