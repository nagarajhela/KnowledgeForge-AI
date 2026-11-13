import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.security import generate_opaque_token, hash_token
from app.models.enums import InvitationStatus, OrganizationRole
from app.models.organization import (
    AuditLog,
    Invitation,
    Organization,
    OrganizationMember,
    Team,
    TeamMember,
)
from app.models.user import User
from app.schemas.organization import (
    InvitationCreateRequest,
    MemberResponse,
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
    OrganizationWithRoleResponse,
    TeamCreateRequest,
)
from app.services.billing_service import BillingService


class OrganizationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_organization(
        self, user: User, payload: OrganizationCreateRequest, ip_address: str | None = None
    ) -> OrganizationWithRoleResponse:
        slug = payload.slug or (
            re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-")[:90]
            + f"-{secrets.token_hex(3)}"
        )
        existing = (
            await self.db.execute(select(Organization).where(Organization.slug == slug))
        ).scalar_one_or_none()
        if existing:
            raise ConflictError("Organization slug already in use")

        org = Organization(
            name=payload.name.strip(),
            slug=slug,
            retention_days=payload.retention_days,
        )
        self.db.add(org)
        await self.db.flush()

        self.db.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=OrganizationRole.OWNER,
            )
        )
        await BillingService(self.db).create_default_subscription(org.id)
        await self.record_audit_log(
            organization_id=org.id,
            actor_user_id=user.id,
            action="organization.created",
            resource_type="organization",
            resource_id=str(org.id),
            ip_address=ip_address,
            metadata={"name": org.name, "slug": org.slug},
        )
        await self.db.commit()
        await self.db.refresh(org)
        return OrganizationWithRoleResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            retention_days=org.retention_days,
            created_at=org.created_at,
            updated_at=org.updated_at,
            role=OrganizationRole.OWNER,
        )

    async def list_user_organizations(self, user_id: uuid.UUID) -> list[OrganizationWithRoleResponse]:
        stmt = (
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == user_id,
                Organization.deleted_at.is_(None),
            )
            .order_by(Organization.created_at.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        return [
            OrganizationWithRoleResponse(
                id=org.id,
                name=org.name,
                slug=org.slug,
                retention_days=org.retention_days,
                created_at=org.created_at,
                updated_at=org.updated_at,
                role=role,
            )
            for org, role in rows
        ]

    async def update_organization(
        self,
        org: Organization,
        actor: User,
        payload: OrganizationUpdateRequest,
    ) -> Organization:
        if payload.name is not None:
            org.name = payload.name.strip()
        if payload.retention_days is not None:
            org.retention_days = payload.retention_days
        await self.record_audit_log(
            organization_id=org.id,
            actor_user_id=actor.id,
            action="organization.updated",
            resource_type="organization",
            resource_id=str(org.id),
        )
        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def delete_organization(self, org: Organization, actor: User) -> None:
        org.deleted_at = datetime.now(UTC)
        await self.record_audit_log(
            organization_id=org.id,
            actor_user_id=actor.id,
            action="organization.deleted",
            resource_type="organization",
            resource_id=str(org.id),
        )
        await self.db.commit()

    async def transfer_ownership(
        self, org_id: uuid.UUID, current_owner: User, new_owner_user_id: uuid.UUID
    ) -> None:
        current_member = (
            await self.db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == current_owner.id,
                )
            )
        ).scalar_one_or_none()
        target_member = (
            await self.db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == new_owner_user_id,
                )
            )
        ).scalar_one_or_none()
        if not target_member:
            raise NotFoundError("Target user is not a member of this organization")
        if current_member:
            current_member.role = OrganizationRole.ADMIN
        target_member.role = OrganizationRole.OWNER
        await self.record_audit_log(
            organization_id=org_id,
            actor_user_id=current_owner.id,
            action="organization.ownership_transferred",
            resource_type="organization_member",
            resource_id=str(new_owner_user_id),
        )
        await self.db.commit()

    async def list_members(self, org_id: uuid.UUID) -> list[MemberResponse]:
        stmt = (
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == org_id, User.deleted_at.is_(None))
            .order_by(OrganizationMember.created_at.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        return [
            MemberResponse(
                id=member.id,
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=member.role,
                created_at=member.created_at,
            )
            for member, user in rows
        ]

    async def change_member_role(
        self,
        org_id: uuid.UUID,
        actor: User,
        target_user_id: uuid.UUID,
        new_role: OrganizationRole,
    ) -> OrganizationMember:
        member = (
            await self.db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == target_user_id,
                )
            )
        ).scalar_one_or_none()
        if not member:
            raise NotFoundError("Organization member not found")
        if member.role == OrganizationRole.OWNER and new_role != OrganizationRole.OWNER:
            raise AuthorizationError("Use ownership transfer to demote an owner")
        member.role = new_role
        await self.record_audit_log(
            organization_id=org_id,
            actor_user_id=actor.id,
            action="member.role_changed",
            resource_type="organization_member",
            resource_id=str(target_user_id),
            metadata={"new_role": new_role.value},
        )
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def remove_member(
        self, org_id: uuid.UUID, actor: User, target_user_id: uuid.UUID
    ) -> None:
        member = (
            await self.db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == target_user_id,
                )
            )
        ).scalar_one_or_none()
        if not member:
            raise NotFoundError("Member not found")
        if member.role == OrganizationRole.OWNER:
            raise AuthorizationError("Cannot remove the organization owner")
        await self.db.delete(member)
        await self.record_audit_log(
            organization_id=org_id,
            actor_user_id=actor.id,
            action="member.removed",
            resource_type="organization_member",
            resource_id=str(target_user_id),
        )
        await self.db.commit()

    async def create_invitation(
        self, org_id: uuid.UUID, inviter: User, payload: InvitationCreateRequest
    ) -> tuple[Invitation, str]:
        await BillingService(self.db).assert_can_invite_member(org_id)
        raw_token, token_hash = generate_opaque_token()
        invite = Invitation(
            organization_id=org_id,
            email=payload.email.lower(),
            role=payload.role,
            token_hash=token_hash,
            status=InvitationStatus.PENDING,
            invited_by=inviter.id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.db.add(invite)
        await self.record_audit_log(
            organization_id=org_id,
            actor_user_id=inviter.id,
            action="invitation.created",
            resource_type="invitation",
            metadata={"email": payload.email.lower(), "role": payload.role.value},
        )
        await self.db.commit()
        await self.db.refresh(invite)
        return invite, raw_token

    async def respond_invitation(
        self, user: User, raw_token: str, *, accept: bool
    ) -> Invitation:
        invite = (
            await self.db.execute(
                select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
            )
        ).scalar_one_or_none()
        if not invite or invite.status != InvitationStatus.PENDING:
            raise NotFoundError("Invitation not found or already processed")
        exp = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=UTC)
        if exp < datetime.now(UTC):
            invite.status = InvitationStatus.EXPIRED
            await self.db.commit()
            raise AuthorizationError("Invitation has expired")
        if invite.email.lower() != user.email.lower():
            raise AuthorizationError("Invitation email does not match authenticated user")

        invite.responded_at = datetime.now(UTC)
        if accept:
            invite.status = InvitationStatus.ACCEPTED
            existing = (
                await self.db.execute(
                    select(OrganizationMember).where(
                        OrganizationMember.organization_id == invite.organization_id,
                        OrganizationMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if not existing:
                self.db.add(
                    OrganizationMember(
                        organization_id=invite.organization_id,
                        user_id=user.id,
                        role=invite.role,
                        invited_by=invite.invited_by,
                    )
                )
        else:
            invite.status = InvitationStatus.DECLINED

        await self.db.commit()
        await self.db.refresh(invite)
        return invite

    async def list_invitations(self, org_id: uuid.UUID) -> list[Invitation]:
        stmt = (
            select(Invitation)
            .where(Invitation.organization_id == org_id)
            .order_by(Invitation.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def create_team(self, org_id: uuid.UUID, actor: User, payload: TeamCreateRequest) -> Team:
        team = Team(
            organization_id=org_id,
            name=payload.name.strip(),
            description=payload.description,
        )
        self.db.add(team)
        await self.record_audit_log(
            organization_id=org_id,
            actor_user_id=actor.id,
            action="team.created",
            resource_type="team",
            metadata={"name": team.name},
        )
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def list_teams(self, org_id: uuid.UUID) -> list[Team]:
        stmt = select(Team).where(Team.organization_id == org_id).order_by(Team.name.asc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def add_team_member(
        self, org_id: uuid.UUID, team_id: uuid.UUID, user_id: uuid.UUID
    ) -> TeamMember:
        team = (
            await self.db.execute(
                select(Team).where(Team.id == team_id, Team.organization_id == org_id)
            )
        ).scalar_one_or_none()
        if not team:
            raise NotFoundError("Team not found")
        member = (
            await self.db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not member:
            raise NotFoundError("User must be an organization member before joining a team")
        tm = TeamMember(organization_id=org_id, team_id=team_id, user_id=user_id)
        self.db.add(tm)
        await self.db.commit()
        await self.db.refresh(tm)
        return tm

    async def list_audit_logs(
        self, org_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.organization_id == org_id)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def record_audit_log(
        self,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                metadata_json=metadata or {},
            )
        )
