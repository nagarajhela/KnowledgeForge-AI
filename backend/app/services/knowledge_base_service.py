import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.models.enums import AccessScope, KnowledgeBaseStatus, OrganizationRole
from app.models.knowledge import KnowledgeBase, KnowledgeBaseAccess
from app.models.organization import TeamMember
from app.models.user import User
from app.repositories.knowledge_repo import KnowledgeBaseRepository
from app.schemas.knowledge_base import (
    KnowledgeBaseAccessAssignRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
)
from app.services.billing_service import BillingService
from app.services.organization_service import OrganizationService


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id
        self.repo = KnowledgeBaseRepository(db, organization_id)

    async def create_kb(self, actor: User, payload: KnowledgeBaseCreateRequest) -> KnowledgeBase:
        await BillingService(self.db).assert_can_create_kb(self.organization_id)
        kb = KnowledgeBase(
            organization_id=self.organization_id,
            created_by=actor.id,
            name=payload.name.strip(),
            description=payload.description,
            system_prompt=payload.system_prompt,
            language=payload.language,
            llm_provider=payload.llm_provider,
            llm_model=payload.llm_model,
            temperature=payload.temperature,
            embedding_provider=payload.embedding_provider,
            embedding_model=payload.embedding_model,
            chunk_size=payload.chunk_size,
            chunk_overlap=min(payload.chunk_overlap, max(0, payload.chunk_size // 2)),
            retrieval_top_k=payload.retrieval_top_k,
            hybrid_alpha=payload.hybrid_alpha,
            rerank_enabled=payload.rerank_enabled,
            min_confidence_score=payload.min_confidence_score,
            access_scope=payload.access_scope,
            status=KnowledgeBaseStatus.ACTIVE,
        )
        self.db.add(kb)
        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=actor.id,
            action="knowledge_base.created",
            resource_type="knowledge_base",
            metadata={"name": kb.name},
        )
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def list_kbs(
        self,
        *,
        user: User,
        role: OrganizationRole,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[KnowledgeBase], int]:
        items, _ = await self.repo.list_paginated(offset=0, limit=500)
        permitted: list[KnowledgeBase] = []
        for kb in items:
            if await self.can_access_kb(kb, user.id, role):
                permitted.append(kb)
        return permitted[offset : offset + limit], len(permitted)

    async def get_kb_for_user(
        self, kb_id: uuid.UUID, *, user: User, role: OrganizationRole
    ) -> KnowledgeBase:
        kb = await self.repo.get_by_id(kb_id)
        if not kb:
            raise NotFoundError("Knowledge base not found")
        if not await self.can_access_kb(kb, user.id, role):
            raise AuthorizationError("You do not have access to this knowledge base")
        return kb

    async def update_kb(
        self,
        kb_id: uuid.UUID,
        actor: User,
        role: OrganizationRole,
        payload: KnowledgeBaseUpdateRequest,
    ) -> KnowledgeBase:
        kb = await self.get_kb_for_user(kb_id, user=actor, role=role)
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(kb, field, value)
        if kb.chunk_overlap >= kb.chunk_size:
            kb.chunk_overlap = max(0, kb.chunk_size // 4)
        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=actor.id,
            action="knowledge_base.updated",
            resource_type="knowledge_base",
            resource_id=str(kb.id),
        )
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def delete_or_archive_kb(
        self, kb_id: uuid.UUID, actor: User, role: OrganizationRole, *, archive_only: bool = True
    ) -> None:
        kb = await self.get_kb_for_user(kb_id, user=actor, role=role)
        if archive_only:
            kb.status = KnowledgeBaseStatus.ARCHIVED
        else:
            kb.deleted_at = datetime.now(UTC)
        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=actor.id,
            action="knowledge_base.archived" if archive_only else "knowledge_base.deleted",
            resource_type="knowledge_base",
            resource_id=str(kb.id),
        )
        await self.db.commit()

    async def assign_access(
        self,
        kb_id: uuid.UUID,
        actor: User,
        role: OrganizationRole,
        payload: KnowledgeBaseAccessAssignRequest,
    ) -> KnowledgeBase:
        kb = await self.get_kb_for_user(kb_id, user=actor, role=role)
        kb.access_scope = payload.access_scope
        await self.db.execute(
            delete(KnowledgeBaseAccess).where(
                KnowledgeBaseAccess.knowledge_base_id == kb.id,
                KnowledgeBaseAccess.organization_id == self.organization_id,
            )
        )
        for uid in payload.user_ids:
            self.db.add(
                KnowledgeBaseAccess(
                    organization_id=self.organization_id,
                    knowledge_base_id=kb.id,
                    user_id=uid,
                )
            )
        for tid in payload.team_ids:
            self.db.add(
                KnowledgeBaseAccess(
                    organization_id=self.organization_id,
                    knowledge_base_id=kb.id,
                    team_id=tid,
                )
            )
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def can_access_kb(
        self, kb: KnowledgeBase, user_id: uuid.UUID, role: OrganizationRole
    ) -> bool:
        if kb.organization_id != self.organization_id:
            return False
        if role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
            return True
        if kb.access_scope == AccessScope.ORGANIZATION_WIDE:
            return True
        if kb.access_scope == AccessScope.SELECTED_USERS:
            entry = (
                await self.db.execute(
                    select(KnowledgeBaseAccess).where(
                        KnowledgeBaseAccess.organization_id == self.organization_id,
                        KnowledgeBaseAccess.knowledge_base_id == kb.id,
                        KnowledgeBaseAccess.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            return entry is not None
        if kb.access_scope == AccessScope.SELECTED_TEAMS:
            team_ids = list(
                (
                    await self.db.execute(
                        select(TeamMember.team_id).where(
                            TeamMember.organization_id == self.organization_id,
                            TeamMember.user_id == user_id,
                        )
                    )
                ).scalars().all()
            )
            if not team_ids:
                return False
            entry = (
                await self.db.execute(
                    select(KnowledgeBaseAccess).where(
                        KnowledgeBaseAccess.organization_id == self.organization_id,
                        KnowledgeBaseAccess.knowledge_base_id == kb.id,
                        KnowledgeBaseAccess.team_id.in_(team_ids),
                    )
                )
            ).scalar_one_or_none()
            return entry is not None
        return False

    async def validate_requested_kbs(
        self, kb_ids: list[uuid.UUID], *, user: User, role: OrganizationRole
    ) -> list[KnowledgeBase]:
        kbs: list[KnowledgeBase] = []
        for kb_id in kb_ids:
            kb = await self.get_kb_for_user(kb_id, user=user, role=role)
            kbs.append(kb)
        return kbs
