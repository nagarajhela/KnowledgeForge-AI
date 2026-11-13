from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.billing import ProviderConfigCreateRequest, ProviderConfigResponse
from app.schemas.common import MessageResponse
from app.services.organization_service import OrganizationService
from app.services.provider_config_service import ProviderConfigService

router = APIRouter(prefix="/provider-configs", tags=["AI Providers"])


@router.get(
    "",
    response_model=list[ProviderConfigResponse],
    summary="List organization AI provider configurations (API keys never returned)",
)
async def list_provider_configs(
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderConfigResponse]:
    rows = await ProviderConfigService(db, tenant.organization_id).list_configs()
    return [ProviderConfigResponse.model_validate(r) for r in rows]


@router.put(
    "",
    response_model=ProviderConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update encrypted AI provider credentials for the active organization",
)
async def upsert_provider_config(
    payload: ProviderConfigCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> ProviderConfigResponse:
    row = await ProviderConfigService(db, tenant.organization_id).upsert_config(payload)
    await OrganizationService(db).log_audit(
        organization_id=tenant.organization_id,
        actor_user_id=tenant.user.id,
        action="provider_config.upsert",
        resource_type="provider_config",
        resource_id=str(row.id),
        metadata={"provider_name": row.provider_name},
    )
    await db.commit()
    return ProviderConfigResponse.model_validate(row)


@router.delete(
    "/{provider_name}",
    response_model=MessageResponse,
    summary="Remove an AI provider configuration from the active organization",
)
async def delete_provider_config(
    provider_name: str,
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await ProviderConfigService(db, tenant.organization_id).delete_config(provider_name)
    await OrganizationService(db).log_audit(
        organization_id=tenant.organization_id,
        actor_user_id=tenant.user.id,
        action="provider_config.delete",
        resource_type="provider_config",
        resource_id=provider_name.lower(),
    )
    await db.commit()
    return MessageResponse(message=f"Provider configuration '{provider_name.lower()}' removed")
