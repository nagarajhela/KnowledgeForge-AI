import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage, ChatSession
from app.repositories.base import TenantRepository


class ChatSessionRepository(TenantRepository[ChatSession]):
    model = ChatSession

    async def get_user_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSession | None:
        stmt = self._base_query().where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_user_sessions(
        self, user_id: uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[ChatSession], int]:
        base = self._base_query().where(ChatSession.user_id == user_id)
        total = int((await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        rows = list(
            (await self.db.execute(base.order_by(ChatSession.updated_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return rows, total


class ChatMessageRepository(TenantRepository[ChatMessage]):
    model = ChatMessage

    async def list_session_messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        stmt = (
            self._base_query()
            .where(ChatMessage.session_id == session_id)
            .options(selectinload(ChatMessage.citations))
            .order_by(ChatMessage.created_at.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())
