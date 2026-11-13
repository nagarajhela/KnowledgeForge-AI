import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.providers.extractors.connectors import CONNECTOR_REGISTRY
from app.repositories.knowledge_repo import IngestionJobRepository
from app.schemas.common import PaginatedResponse
from app.schemas.document import IngestionJobResponse, IngestionTriggerRequest
from app.services.document_service import DocumentService

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.get(
    "/jobs",
    response_model=PaginatedResponse[IngestionJobResponse],
    summary="List document ingestion jobs for the active organization",
)
async def list_ingestion_jobs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[IngestionJobResponse]:
    items, total = await IngestionJobRepository(db, tenant.organization_id).list_paginated(
        offset=offset, limit=limit
    )
    return PaginatedResponse(
        items=[IngestionJobResponse.model_validate(j) for j in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=IngestionJobResponse,
    summary="Get ingestion job status scoped to the active organization",
)
async def get_ingestion_job(
    job_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
    db: AsyncSession = Depends(get_db),
) -> IngestionJobResponse:
    job = await IngestionJobRepository(db, tenant.organization_id).get_by_id(job_id)
    if not job:
        raise NotFoundError("Ingestion job not found")
    return IngestionJobResponse.model_validate(job)


@router.post(
    "/jobs",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger ingestion job for a tenant-owned document",
)
async def trigger_ingestion_job(
    payload: IngestionTriggerRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
) -> IngestionJobResponse:
    _, job = await DocumentService(db, tenant.organization_id).reprocess_document(
        payload.document_id, user=tenant.user, role=tenant.role
    )
    return IngestionJobResponse.model_validate(job)


@router.get("/connectors", summary="List available external knowledge connectors")
async def list_connectors(
    tenant: TenantContext = Depends(require_permissions(Permission.KB_READ)),
) -> dict:
    return {
        "organization_id": str(tenant.organization_id),
        "connectors": [
            {"provider": name, "status": "available_adapter"}
            for name in sorted(CONNECTOR_REGISTRY.keys())
        ],
    }
