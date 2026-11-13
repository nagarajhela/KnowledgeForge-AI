import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.common import MessageResponse
from app.schemas.organization import MemberResponse, MemberRoleUpdateRequest
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("", response_model=list[MemberResponse], summary="List members of the active organization")
async def list_members(
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    return await OrganizationService(db).list_members(tenant.organization_id)


@router.patch("/{user_id}/role", response_model=MessageResponse, summary="Update a member's RBAC role")
async def update_member_role(
    user_id: uuid.UUID,
    payload: MemberRoleUpdateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await OrganizationService(db).change_member_role(
        tenant.organization_id, tenant.user, user_id, payload.role
    )
    return MessageResponse(message="Member role updated")


@router.delete("/{user_id}", response_model=MessageResponse, summary="Remove a member from organization")
async def remove_member(
    user_id: uuid.UUID,
    tenant: TenantContext = Depends(require_permissions(Permission.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await OrganizationService(db).remove_member(tenant.organization_id, tenant.user, user_id)
    return MessageResponse(message="Member removed")
