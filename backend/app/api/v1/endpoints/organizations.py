import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import Permission
from app.core.tenant import TenantContext, get_current_user, require_permissions
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.organization import (
    AuditLogResponse,
    InvitationCreateRequest,
    InvitationCreatedResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrganizationWithRoleResponse,
    TransferOwnershipRequest,
)
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.get(
    "",
    response_model=list[OrganizationWithRoleResponse],
    summary="List organizations the current user belongs to",
)
async def list_organizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationWithRoleResponse]:
    return await OrganizationService(db).list_user_organizations(user.id)


@router.post(
    "",
    response_model=OrganizationWithRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant organization",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationWithRoleResponse:
    ip = request.client.host if request.client else None
    return await OrganizationService(db).create_organization(user, payload, ip_address=ip)


@router.get(
    "/current",
    response_model=OrganizationWithRoleResponse,
    summary="Get active tenant resolved via X-Organization-ID or API key",
)
async def get_current_organization(
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_READ)),
) -> OrganizationWithRoleResponse:
    return OrganizationWithRoleResponse(
        id=tenant.organization.id,
        name=tenant.organization.name,
        slug=tenant.organization.slug,
        retention_days=tenant.organization.retention_days,
        created_at=tenant.organization.created_at,
        updated_at=tenant.organization.updated_at,
        role=tenant.role,
    )


@router.patch(
    "/current",
    response_model=OrganizationResponse,
    summary="Update active organization settings",
)
async def update_current_organization(
    payload: OrganizationUpdateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    org = await OrganizationService(db).update_organization(
        tenant.organization, tenant.user, payload
    )
    return OrganizationResponse.model_validate(org)


@router.delete(
    "/current",
    response_model=MessageResponse,
    summary="Soft-delete active organization (owner only)",
)
async def delete_current_organization(
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_DELETE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await OrganizationService(db).delete_organization(tenant.organization, tenant.user)
    return MessageResponse(message="Organization deleted")


@router.post(
    "/current/transfer-ownership",
    response_model=MessageResponse,
    summary="Transfer organization ownership to another member",
)
async def transfer_ownership(
    payload: TransferOwnershipRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_TRANSFER)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await OrganizationService(db).transfer_ownership(
        tenant.organization_id, tenant.user, payload.new_owner_user_id
    )
    return MessageResponse(message="Ownership transferred successfully")


@router.post(
    "/{organization_id}/invite",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user by email to the organization",
)
async def invite_to_organization(
    organization_id: uuid.UUID,
    payload: InvitationCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> InvitationCreatedResponse:
    if organization_id != tenant.organization_id:
        raise AuthorizationError("Path organization_id does not match active organization")
    invite, raw_token = await OrganizationService(db).create_invitation(
        tenant.organization_id, tenant.user, payload
    )
    return InvitationCreatedResponse(
        id=invite.id,
        organization_id=invite.organization_id,
        email=invite.email,
        role=invite.role,
        status=invite.status,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        invite_token=raw_token,
    )


@router.get(
    "/current/audit-logs",
    response_model=list[AuditLogResponse],
    summary="List organization audit logs",
)
async def get_audit_logs(
    offset: int = 0,
    limit: int = 50,
    tenant: TenantContext = Depends(require_permissions(Permission.AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogResponse]:
    logs = await OrganizationService(db).list_audit_logs(
        tenant.organization_id, offset=offset, limit=limit
    )
    return [AuditLogResponse.model_validate(log) for log in logs]
