from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, get_current_user, require_permissions
from app.db.session import get_db
from app.models.user import User
from app.schemas.organization import (
    InvitationCreateRequest,
    InvitationCreatedResponse,
    InvitationRespondRequest,
    InvitationResponse,
)
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/invitations", tags=["Invitations"])


@router.get("", response_model=list[InvitationResponse], summary="List organization invitations")
async def list_invitations(
    tenant: TenantContext = Depends(require_permissions(Permission.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationResponse]:
    invites = await OrganizationService(db).list_invitations(tenant.organization_id)
    return [InvitationResponse.model_validate(i) for i in invites]


@router.post(
    "",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invitation in the active organization",
)
async def create_invitation(
    payload: InvitationCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> InvitationCreatedResponse:
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


@router.post("/accept", response_model=InvitationResponse, summary="Accept an organization invitation")
async def accept_invitation(
    payload: InvitationRespondRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    invite = await OrganizationService(db).respond_invitation(user, payload.token, accept=True)
    return InvitationResponse.model_validate(invite)


@router.post("/decline", response_model=InvitationResponse, summary="Decline an organization invitation")
async def decline_invitation(
    payload: InvitationRespondRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    invite = await OrganizationService(db).respond_invitation(user, payload.token, accept=False)
    return InvitationResponse.model_validate(invite)
