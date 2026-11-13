import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.common import MessageResponse
from app.schemas.organization import TeamCreateRequest, TeamMemberAddRequest, TeamResponse
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.get("", response_model=list[TeamResponse], summary="List organization teams")
async def list_teams(
    tenant: TenantContext = Depends(require_permissions(Permission.ORG_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[TeamResponse]:
    teams = await OrganizationService(db).list_teams(tenant.organization_id)
    return [TeamResponse.model_validate(t) for t in teams]


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED, summary="Create a team")
async def create_team(
    payload: TeamCreateRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.TEAM_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> TeamResponse:
    team = await OrganizationService(db).create_team(tenant.organization_id, tenant.user, payload)
    return TeamResponse.model_validate(team)


@router.post("/{team_id}/members", response_model=MessageResponse, summary="Add member to team")
async def add_team_member(
    team_id: uuid.UUID,
    payload: TeamMemberAddRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.TEAM_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await OrganizationService(db).add_team_member(
        tenant.organization_id, team_id, payload.user_id
    )
    return MessageResponse(message="User added to team")
