import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import (
    Base,
    EmbeddingVector,
    SearchTSVector,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDMixin,
)
from app.models.enums import (
    AccessScope,
    DocumentStatus,
    IngestionJobStatus,
    KnowledgeBaseStatus,
    SourceType,
)


class KnowledgeBase(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        Index("ix_kb_org_status", "organization_id", "status"),
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(32), default="en", nullable=False)

    llm_provider: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(120), default="gpt-4o-mini", nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)

    embedding_provider: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(120), default="text-embedding-3-small", nullable=False
    )

    chunk_size: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=64, nullable=False)

    retrieval_top_k: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    hybrid_alpha: Mapped[float] = mapped_column(Float, default=0.65, nullable=False)
    rerank_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    min_confidence_score: Mapped[float] = mapped_column(Float, default=0.35, nullable=False)

    access_scope: Mapped[AccessScope] = mapped_column(
        SAEnum(AccessScope, name="kb_access_scope", native_enum=False),
        default=AccessScope.ORGANIZATION_WIDE,
        nullable=False,
    )
    status: Mapped[KnowledgeBaseStatus] = mapped_column(
        SAEnum(KnowledgeBaseStatus, name="kb_status", native_enum=False),
        default=KnowledgeBaseStatus.ACTIVE,
        nullable=False,
    )

    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    access_entries = relationship(
        "KnowledgeBaseAccess", back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class KnowledgeBaseAccess(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "knowledge_base_access"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "user_id", name="uq_kb_access_user"),
        UniqueConstraint("knowledge_base_id", "team_id", name="uq_kb_access_team"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="access_entries")


class Document(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_org_kb_status", "organization_id", "knowledge_base_id", "processing_status"),
        Index("ix_documents_org_checksum", "organization_id", "knowledge_base_id", "checksum"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, name="document_source_type", native_enum=False),
        default=SourceType.UPLOAD,
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, name="document_status", native_enum=False),
        default=DocumentStatus.QUEUED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    ingestion_jobs = relationship("IngestionJob", back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_doc_version_number"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    document = relationship("Document", back_populates="versions")


class DocumentChunk(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_chunks_org_kb", "organization_id", "knowledge_base_id"),
        Index("ix_chunks_doc_index", "document_id", "chunk_index"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(settings.EMBEDDING_DIMENSIONS), nullable=True
    )
    search_vector: Mapped[str | None] = mapped_column(SearchTSVector(), nullable=True)

    document = relationship("Document", back_populates="chunks")


class IngestionJob(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_org_status", "organization_id", "status"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[IngestionJobStatus] = mapped_column(
        SAEnum(IngestionJobStatus, name="ingestion_job_status", native_enum=False),
        default=IngestionJobStatus.QUEUED,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="ingestion_jobs")
