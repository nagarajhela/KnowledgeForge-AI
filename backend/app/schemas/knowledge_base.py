import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AccessScope, KnowledgeBaseStatus
from app.schemas.common import ORMModel


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    language: str = Field(default="en", max_length=32)
    llm_provider: str = Field(default="mock", max_length=64)
    llm_model: str = Field(default="gpt-4o-mini", max_length=120)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    embedding_provider: str = Field(default="mock", max_length=64)
    embedding_model: str = Field(default="text-embedding-3-small", max_length=120)
    chunk_size: int = Field(default=512, ge=100, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=1024)
    retrieval_top_k: int = Field(default=6, ge=1, le=30)
    hybrid_alpha: float = Field(default=0.65, ge=0.0, le=1.0)
    rerank_enabled: bool = True
    min_confidence_score: float = Field(default=0.35, ge=0.0, le=1.0)
    access_scope: AccessScope = AccessScope.ORGANIZATION_WIDE


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    language: str | None = Field(default=None, max_length=32)
    llm_provider: str | None = Field(default=None, max_length=64)
    llm_model: str | None = Field(default=None, max_length=120)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    embedding_provider: str | None = Field(default=None, max_length=64)
    embedding_model: str | None = Field(default=None, max_length=120)
    chunk_size: int | None = Field(default=None, ge=100, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1024)
    retrieval_top_k: int | None = Field(default=None, ge=1, le=30)
    hybrid_alpha: float | None = Field(default=None, ge=0.0, le=1.0)
    rerank_enabled: bool | None = None
    min_confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    access_scope: AccessScope | None = None
    status: KnowledgeBaseStatus | None = None


class KnowledgeBaseAccessAssignRequest(BaseModel):
    access_scope: AccessScope
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    team_ids: list[uuid.UUID] = Field(default_factory=list)


class KnowledgeBaseResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by: uuid.UUID | None
    name: str
    description: str | None
    system_prompt: str | None
    language: str
    llm_provider: str
    llm_model: str
    temperature: float
    embedding_provider: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int
    hybrid_alpha: float
    rerank_enabled: bool
    min_confidence_score: float
    access_scope: AccessScope
    status: KnowledgeBaseStatus
    created_at: datetime
    updated_at: datetime
