import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import DocumentStatus, IngestionJobStatus, SourceType
from app.models.knowledge import Document, DocumentChunk, IngestionJob
from app.providers.embeddings import get_embedding_provider
from app.providers.extractors import fetch_and_extract_url, get_extractor
from app.repositories.knowledge_repo import (
    DocumentChunkRepository,
    DocumentRepository,
    IngestionJobRepository,
    KnowledgeBaseRepository,
)
from app.services.chunking_service import ChunkingService
from app.services.provider_config_service import ProviderConfigService
from app.services.storage_service import StorageService


class IngestionService:
    """Executes the end-to-end document extraction, normalization, chunking, and embedding pipeline."""

    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id
        self.doc_repo = DocumentRepository(db, organization_id)
        self.kb_repo = KnowledgeBaseRepository(db, organization_id)
        self.chunk_repo = DocumentChunkRepository(db, organization_id)
        self.job_repo = IngestionJobRepository(db, organization_id)
        self.storage = StorageService()
        self.chunker = ChunkingService()
        self.provider_configs = ProviderConfigService(db, organization_id)

    async def process_document(
        self,
        document_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
    ) -> Document:
        doc = await self.doc_repo.get_by_id(document_id)
        if not doc or doc.organization_id != self.organization_id:
            raise NotFoundError("Document not found in organization")

        kb = await self.kb_repo.get_by_id(doc.knowledge_base_id)
        if not kb or kb.organization_id != self.organization_id:
            raise NotFoundError("Knowledge base not found in organization")

        job: IngestionJob | None = None
        if job_id:
            job = await self.job_repo.get_by_id(job_id)
            if not job or job.organization_id != self.organization_id or job.document_id != doc.id:
                raise NotFoundError("Ingestion job not found in organization")
        if job:
            job.status = IngestionJobStatus.RUNNING
            job.attempt_count += 1
            job.started_at = datetime.now(UTC)
            job.error_message = None

        doc.processing_status = DocumentStatus.PROCESSING
        doc.error_message = None
        await self.db.commit()

        try:
            if doc.source_type == SourceType.URL and doc.source_url:
                extracted = await fetch_and_extract_url(doc.source_url)
                raw_bytes = extracted.full_text.encode("utf-8")
                doc.checksum = doc.checksum or hashlib.sha256(raw_bytes).hexdigest()
                doc.file_size_bytes = len(raw_bytes)
            else:
                if not doc.storage_path:
                    raise ValueError("Missing storage_path for uploaded document")
                raw_bytes = await self.storage.load_document_bytes(doc.storage_path)
                doc.checksum = doc.checksum or hashlib.sha256(raw_bytes).hexdigest()
                extractor = get_extractor(doc.filename, doc.mime_type)
                extracted = extractor.extract(raw_bytes, filename=doc.filename)

            full_text = extracted.full_text
            if not full_text.strip():
                raise ValueError("No extractable text content found in document")

            doc.language = self.chunker.detect_language(full_text)
            doc.page_count = extracted.page_count

            chunks = self.chunker.chunk_document(
                extracted,
                chunk_size=kb.chunk_size,
                chunk_overlap=kb.chunk_overlap,
            )

            await self.chunk_repo.delete_by_document(doc.id)
            await self.db.flush()

            embed_creds = await self.provider_configs.resolve_credentials(kb.embedding_provider)
            embedder = get_embedding_provider(
                kb.embedding_provider,
                model=kb.embedding_model,
                api_key=embed_creds.api_key,
                base_url=embed_creds.base_url,
            )
            vectors = await embedder.embed_texts([c.content for c in chunks])

            is_pg = bool(self.db.bind and self.db.bind.dialect.name == "postgresql")
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk_row = DocumentChunk(
                    organization_id=self.organization_id,
                    knowledge_base_id=kb.id,
                    document_id=doc.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    metadata_json={
                        "filename": doc.filename,
                        "source_type": doc.source_type.value,
                        "source_url": doc.source_url,
                        "language": doc.language,
                    },
                    embedding=vector,
                )
                self.db.add(chunk_row)
                await self.db.flush()
                if is_pg:
                    chunk_row.search_vector = func.to_tsvector("english", chunk.content)  # type: ignore[assignment]

            doc.chunk_count = len(chunks)
            doc.processing_status = DocumentStatus.COMPLETED
            if job:
                job.status = IngestionJobStatus.COMPLETED
                job.completed_at = datetime.now(UTC)

            await self.db.commit()
            await self.db.refresh(doc)
            return doc

        except Exception as exc:
            await self.db.rollback()
            safe_err = f"{type(exc).__name__}: {str(exc)[:500]}"
            doc = await self.doc_repo.get_by_id(document_id)
            if doc:
                doc.processing_status = DocumentStatus.FAILED
                doc.error_message = safe_err
            if job_id:
                job = await self.job_repo.get_by_id(job_id)
                if job:
                    job.status = IngestionJobStatus.FAILED
                    job.error_message = safe_err
                    job.completed_at = datetime.now(UTC)
            await self.db.commit()
            raise
