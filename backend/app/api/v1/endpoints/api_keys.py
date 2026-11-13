import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.billing import APIKeyCreateRequest, APIKeyCreatedResponse, APIKeyResponse
from app.services.api_key_service import APIKeyService

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


@router.get("", response_model=list[APIKeyResponse], summary="List organization API keys")
async def list_api_keys(
    tenant: TenantContext = Depends(require_permissions(Permission.API_KEY_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyResponse]:
    keys = await APIKeyService(db, tenant.organization_id).list_keys()
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.post(
    "",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scoped API key (plaintext shown once)",
)
async def create_api_key(
    payload: APIKeyCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.API_KEY_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreatedResponse:
    return await APIKeyService(db, tenant.organization_id).create_key(tenant.user.id, payload)


@router.delete("/{key_id}", response_model=APIKeyResponse, summary="Revoke an API key")
async def revoke_api_key(
    key_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.API_KEY_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> APIKeyResponse:
    key = await APIKeyService(db, tenant.organization_id).revoke_key(key_id, tenant.user.id)
    return APIKeyResponse.model_validate(key)
