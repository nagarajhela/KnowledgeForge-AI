import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.enums import DocumentStatus, IngestionJobStatus, OrganizationRole, SourceType
from app.models.knowledge import Document, DocumentVersion, IngestionJob
from app.models.user import User
from app.repositories.knowledge_repo import DocumentRepository, IngestionJobRepository
from app.schemas.document import DocumentURLIngestRequest
from app.services.billing_service import BillingService
from app.services.ingestion_service import IngestionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.organization_service import OrganizationService
from app.services.storage_service import StorageService


class DocumentService:
    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id
        self.repo = DocumentRepository(db, organization_id)
        self.job_repo = IngestionJobRepository(db, organization_id)
        self.kb_service = KnowledgeBaseService(db, organization_id)
        self.storage = StorageService()

    async def upload_file(
        self,
        *,
        kb_id: uuid.UUID,
        actor: User,
        role: OrganizationRole,
        filename: str,
        content_type: str,
        data: bytes,
        idempotency_key: str | None = None,
        run_inline: bool = False,
    ) -> tuple[Document, IngestionJob, bool]:
        await self.kb_service.get_kb_for_user(kb_id, user=actor, role=role)
        await BillingService(self.db).assert_can_upload_document(self.organization_id, len(data))

        if idempotency_key:
            existing_idem = await self.repo.get_by_idempotency_key(kb_id, idempotency_key)
            if existing_idem:
                jobs = await self.job_repo.list_by_document(existing_idem.id)
                job = jobs[0] if jobs else await self._create_job(kb_id, existing_idem.id)
                return existing_idem, job, True

        checksum = self.storage.compute_sha256(data)
        duplicate = await self.repo.get_by_checksum(kb_id, checksum)
        if duplicate:
            jobs = await self.job_repo.list_by_document(duplicate.id)
            job = jobs[0] if jobs else await self._create_job(kb_id, duplicate.id)
            return duplicate, job, True

        doc_id = uuid.uuid4()
        storage_path, checksum, validated_mime = await self.storage.store_document_bytes(
            organization_id=self.organization_id,
            knowledge_base_id=kb_id,
            document_id=doc_id,
            filename=filename,
            content_type=content_type,
            data=data,
        )

        doc = Document(
            id=doc_id,
            organization_id=self.organization_id,
            knowledge_base_id=kb_id,
            created_by=actor.id,
            filename=self.storage.sanitize_filename(filename),
            mime_type=validated_mime,
            storage_path=storage_path,
            file_size_bytes=len(data),
            source_type=SourceType.UPLOAD,
            checksum=checksum,
            processing_status=DocumentStatus.QUEUED,
            idempotency_key=idempotency_key,
        )
        self.db.add(doc)
        self.db.add(
            DocumentVersion(
                organization_id=self.organization_id,
                document_id=doc.id,
                version_number=1,
                storage_path=storage_path,
                checksum=checksum,
                file_size_bytes=len(data),
                created_by=actor.id,
            )
        )
        await self.db.flush()
        job = await self._create_job(kb_id, doc.id)

        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=actor.id,
            action="document.uploaded",
            resource_type="document",
            resource_id=str(doc.id),
            metadata={"filename": doc.filename, "size_bytes": len(data)},
        )
        await self.db.commit()
        await self.db.refresh(doc)
        await self.db.refresh(job)

        await self._dispatch_ingestion(doc.id, job.id, run_inline=run_inline)
        await self.db.refresh(doc)
        await self.db.refresh(job)
        return doc, job, False

    async def ingest_url(
        self,
        *,
        kb_id: uuid.UUID,
        actor: User,
        role: OrganizationRole,
        payload: DocumentURLIngestRequest,
        run_inline: bool = False,
    ) -> tuple[Document, IngestionJob, bool]:
        await self.kb_service.get_kb_for_user(kb_id, user=actor, role=role)
        await BillingService(self.db).assert_can_upload_document(self.organization_id, 0)

        url_str = str(payload.url)
        checksum = hashlib.sha256(url_str.encode("utf-8")).hexdigest()
        duplicate = await self.repo.get_by_checksum(kb_id, checksum)
        if duplicate:
            jobs = await self.job_repo.list_by_document(duplicate.id)
            job = jobs[0] if jobs else await self._create_job(kb_id, duplicate.id)
            return duplicate, job, True

        doc = Document(
            organization_id=self.organization_id,
            knowledge_base_id=kb_id,
            created_by=actor.id,
            filename=payload.title or url_str[:240],
            mime_type="text/html",
            source_type=SourceType.URL,
            source_url=url_str,
            checksum=checksum,
            processing_status=DocumentStatus.QUEUED,
            metadata_json=payload.metadata,
        )
        self.db.add(doc)
        await self.db.flush()
        job = await self._create_job(kb_id, doc.id)
        await self.db.commit()
        await self.db.refresh(doc)
        await self.db.refresh(job)

        await self._dispatch_ingestion(doc.id, job.id, run_inline=run_inline)
        await self.db.refresh(doc)
        await self.db.refresh(job)
        return doc, job, False

    async def list_documents(
        self, kb_id: uuid.UUID, *, user: User, role: OrganizationRole, offset: int = 0, limit: int = 20
    ) -> tuple[list[Document], int]:
        await self.kb_service.get_kb_for_user(kb_id, user=user, role=role)
        return await self.repo.list_by_kb(kb_id, offset=offset, limit=limit)

    async def list_all_documents(
        self, *, user: User, role: OrganizationRole, offset: int = 0, limit: int = 20
    ) -> tuple[list[Document], int]:
        permitted_kbs, _ = await self.kb_service.list_kbs(user=user, role=role, offset=0, limit=500)
        permitted_ids = {kb.id for kb in permitted_kbs}
        items, _ = await self.repo.list_paginated(offset=0, limit=500)
        filtered = [d for d in items if d.knowledge_base_id in permitted_ids]
        return filtered[offset : offset + limit], len(filtered)

    async def get_document(
        self, document_id: uuid.UUID, *, user: User | None = None, role: OrganizationRole | None = None
    ) -> Document:
        doc = await self.repo.get_by_id(document_id)
        if not doc or doc.organization_id != self.organization_id:
            raise NotFoundError("Document not found")
        if user is not None and role is not None:
            await self.kb_service.get_kb_for_user(doc.knowledge_base_id, user=user, role=role)
        return doc

    async def reprocess_document(
        self,
        document_id: uuid.UUID,
        *,
        user: User | None = None,
        role: OrganizationRole | None = None,
        run_inline: bool = False,
    ) -> tuple[Document, IngestionJob]:
        doc = await self.get_document(document_id, user=user, role=role)
        doc.processing_status = DocumentStatus.QUEUED
        doc.error_message = None
        job = await self._create_job(doc.knowledge_base_id, doc.id)
        await self.db.commit()
        await self.db.refresh(job)
        await self._dispatch_ingestion(doc.id, job.id, run_inline=run_inline)
        await self.db.refresh(doc)
        await self.db.refresh(job)
        return doc, job

    async def delete_document(
        self, document_id: uuid.UUID, actor: User, *, role: OrganizationRole | None = None
    ) -> None:
        doc = await self.get_document(document_id, user=actor, role=role)
        doc.deleted_at = datetime.now(UTC)
        doc.processing_status = DocumentStatus.ARCHIVED
        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=actor.id,
            action="document.deleted",
            resource_type="document",
            resource_id=str(doc.id),
        )
        await self.db.commit()

    async def get_download_url(
        self, document_id: uuid.UUID, *, user: User | None = None, role: OrganizationRole | None = None
    ) -> str:
        doc = await self.get_document(document_id, user=user, role=role)
        if not doc.storage_path:
            raise NotFoundError("No stored file binary for this document")
        return await self.storage.get_signed_download_url(doc.storage_path)

    async def _create_job(self, kb_id: uuid.UUID, document_id: uuid.UUID) -> IngestionJob:
        job = IngestionJob(
            organization_id=self.organization_id,
            knowledge_base_id=kb_id,
            document_id=document_id,
            status=IngestionJobStatus.QUEUED,
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def _dispatch_ingestion(
        self, document_id: uuid.UUID, job_id: uuid.UUID, *, run_inline: bool = False
    ) -> None:
        if run_inline or settings.APP_ENV == "test":
            await IngestionService(self.db, self.organization_id).process_document(
                document_id, job_id=job_id
            )
            return

        try:
            from app.workers.tasks import ingest_document_task

            result = ingest_document_task.delay(
                str(self.organization_id), str(document_id), str(job_id)
            )
            job = await self.job_repo.get_by_id(job_id)
            if job:
                job.celery_task_id = result.id
                await self.db.commit()
        except Exception:
            # Graceful fallback if broker is unreachable in local single-process dev
            await IngestionService(self.db, self.organization_id).process_document(
                document_id, job_id=job_id
            )
