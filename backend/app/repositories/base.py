import uuid
from typing import Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantRepository(Generic[ModelT]):
    """
    Base repository enforcing mandatory organization_id filtering on every read/write query.
    Prevents accidental cross-tenant data leaks at the data-access boundary.
    """

    model: type[ModelT]

    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    def _base_query(self) -> Select[tuple[ModelT]]:
        stmt = select(self.model).where(self.model.organization_id == self.organization_id)  # type: ignore[attr-defined]
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = self._base_query().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_paginated(self, *, offset: int = 0, limit: int = 20) -> tuple[list[ModelT], int]:
        base = self._base_query()
        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self.db.execute(count_stmt)).scalar_one())
        rows_stmt = base.offset(offset).limit(limit)
        if hasattr(self.model, "created_at"):
            rows_stmt = rows_stmt.order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
        items = list((await self.db.execute(rows_stmt)).scalars().all())
        return items, total
