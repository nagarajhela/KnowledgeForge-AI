import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.enums import DocumentStatus, IngestionJobStatus, SourceType
from app.schemas.common import ORMModel


class DocumentURLIngestRequest(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=512)
    metadata: dict = Field(default_factory=dict)


class DocumentResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    created_by: uuid.UUID | None
    filename: str
    mime_type: str
    storage_path: str | None
    file_size_bytes: int
    source_type: SourceType
    source_url: str | None
    checksum: str | None
    language: str | None
    page_count: int
    chunk_count: int
    processing_status: DocumentStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    ingestion_job_id: uuid.UUID
    deduplicated: bool = False


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    knowledge_base_ids: list[uuid.UUID] | None = None
    top_k: int = Field(default=6, ge=1, le=25)
    metadata_filters: dict[str, str] = Field(default_factory=dict)


class DocumentChunkSearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    document_name: str
    content: str
    page_number: int | None
    source_url: str | None
    relevance_score: float


class DocumentSearchResponse(BaseModel):
    results: list[DocumentChunkSearchResult]
    total: int


class IngestionTriggerRequest(BaseModel):
    document_id: uuid.UUID


class IngestionJobResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    document_id: uuid.UUID
    celery_task_id: str | None
    status: IngestionJobStatus
    attempt_count: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class SignedDownloadResponse(BaseModel):
    document_id: uuid.UUID
    download_url: str
    expires_in_seconds: int
