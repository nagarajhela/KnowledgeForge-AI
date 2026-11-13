import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.logging import get_logger
from app.models.knowledge import Document
from app.models.organization import Organization
from app.services.ingestion_service import IngestionService
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@asynccontextmanager
async def _worker_session() -> AsyncSession:
    """Creates a loop-local NullPool engine per task run so prefork workers never share asyncpg loops."""
    worker_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=worker_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with session_factory() as session:
            yield session
    finally:
        await worker_engine.dispose()


async def _run_ingestion(organization_id: str, document_id: str, job_id: str) -> dict[str, str]:
    org_uuid = uuid.UUID(organization_id)
    doc_uuid = uuid.UUID(document_id)
    job_uuid = uuid.UUID(job_id)
    async with _worker_session() as session:
        service = IngestionService(session, org_uuid)
        doc = await service.process_document(doc_uuid, job_id=job_uuid)
        return {"document_id": str(doc.id), "status": doc.processing_status.value}


@celery_app.task(
    bind=True,
    name="app.workers.tasks.ingest_document_task",
    max_retries=3,
    default_retry_delay=15,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    queue="ingestion",
)
def ingest_document_task(
    self: Task, organization_id: str, document_id: str, job_id: str
) -> dict[str, str]:
    try:
        return asyncio.run(_run_ingestion(organization_id, document_id, job_id))
    except (NotFoundError, AuthorizationError) as exc:
        logger.warning(
            "Rejected tenant-mismatched ingestion task",
            extra={"extra_data": {"organization_id": organization_id, "error_code": exc.error_code}},
        )
        raise
    except Exception as exc:
        logger.error(
            "Ingestion task failed",
            extra={"extra_data": {"document_id": document_id, "attempt": self.request.retries, "error": str(exc)}},
        )
        raise self.retry(exc=exc, countdown=min(300, 15 * (2**self.request.retries))) from exc


async def _run_retention_sweep() -> int:
    archived_count = 0
    async with _worker_session() as session:
        orgs = (
            await session.execute(select(Organization).where(Organization.deleted_at.is_(None)))
        ).scalars().all()
        now = datetime.now(UTC)
        for org in orgs:
            cutoff = now - timedelta(days=org.retention_days)
            docs = (
                await session.execute(
                    select(Document).where(
                        Document.organization_id == org.id,
                        Document.deleted_at.is_not(None),
                        Document.deleted_at < cutoff,
                    )
                )
            ).scalars().all()
            for doc in docs:
                await session.delete(doc)
                archived_count += 1
        await session.commit()
    return archived_count


@celery_app.task(name="app.workers.tasks.enforce_retention_policies_task", queue="maintenance")
def enforce_retention_policies_task() -> dict[str, int]:
    purged = asyncio.run(_run_retention_sweep())
    return {"purged_documents": purged}
