import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk, IngestionJob, KnowledgeBase
from app.repositories.base import TenantRepository


class KnowledgeBaseRepository(TenantRepository[KnowledgeBase]):
    model = KnowledgeBase


class DocumentRepository(TenantRepository[Document]):
    model = Document

    async def get_by_checksum(
        self, knowledge_base_id: uuid.UUID, checksum: str
    ) -> Document | None:
        stmt = self._base_query().where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.checksum == checksum,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_idempotency_key(
        self, knowledge_base_id: uuid.UUID, idempotency_key: str
    ) -> Document | None:
        stmt = self._base_query().where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.idempotency_key == idempotency_key,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_kb(
        self, knowledge_base_id: uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Document], int]:
        base = self._base_query().where(Document.knowledge_base_id == knowledge_base_id)
        total = int((await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        rows = list(
            (await self.db.execute(base.order_by(Document.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return rows, total


class DocumentChunkRepository(TenantRepository[DocumentChunk]):
    model = DocumentChunk

    async def delete_by_document(self, document_id: uuid.UUID) -> None:
        chunks = (
            await self.db.execute(
                self._base_query().where(DocumentChunk.document_id == document_id)
            )
        ).scalars().all()
        for chunk in chunks:
            await self.db.delete(chunk)


class IngestionJobRepository(TenantRepository[IngestionJob]):
    model = IngestionJob

    async def list_by_document(self, document_id: uuid.UUID) -> list[IngestionJob]:
        stmt = (
            self._base_query()
            .where(IngestionJob.document_id == document_id)
            .order_by(IngestionJob.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())
