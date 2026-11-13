import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import InvitationStatus, OrganizationRole
from app.schemas.common import ORMModel


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, min_length=2, max_length=120, pattern=r"^[a-z0-9-]+$")
    retention_days: int = Field(default=365, ge=7, le=3650)


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    retention_days: int | None = Field(default=None, ge=7, le=3650)


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: uuid.UUID


class OrganizationResponse(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    retention_days: int
    created_at: datetime
    updated_at: datetime


class OrganizationWithRoleResponse(OrganizationResponse):
    role: OrganizationRole


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: OrganizationRole
    created_at: datetime


class MemberRoleUpdateRequest(BaseModel):
    role: OrganizationRole


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: OrganizationRole = OrganizationRole.VIEWER


class InvitationResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: OrganizationRole
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime


class InvitationCreatedResponse(InvitationResponse):
    invite_token: str


class InvitationRespondRequest(BaseModel):
    token: str


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class TeamMemberAddRequest(BaseModel):
    user_id: uuid.UUID


class TeamResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class AuditLogResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    ip_address: str | None
    metadata_json: dict
    created_at: datetime
