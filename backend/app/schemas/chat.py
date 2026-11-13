import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import FeedbackRating, MessageRole
from app.schemas.common import ORMModel


class ChatSessionCreateRequest(BaseModel):
    title: str = Field(default="New Conversation", min_length=1, max_length=255)
    knowledge_base_ids: list[uuid.UUID] = Field(min_length=1)


class ChatSessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatSessionResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    knowledge_base_ids: list[str]
    created_at: datetime
    updated_at: datetime


class CitationResponse(BaseModel):
    document_id: uuid.UUID
    document_name: str
    chunk_id: uuid.UUID
    page_number: int | None
    source_url: str | None
    excerpt: str
    relevance_score: float


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    knowledge_base_ids: list[uuid.UUID] | None = None
    metadata_filters: dict[str, str] = Field(default_factory=dict)
    top_k: int | None = Field(default=None, ge=1, le=25)


class ChatAnswerResponse(BaseModel):
    message_id: uuid.UUID
    answer: str
    citations: list[CitationResponse]
    confidence_score: float
    insufficient_context: bool = False
    suggested_followups: list[str] = Field(default_factory=list)
    model_used: str | None = None
    provider_used: str | None = None


class ChatMessageResponse(ORMModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    model_used: str | None
    provider_used: str | None
    prompt_tokens: int
    completion_tokens: int
    confidence_score: float | None
    suggested_followups: list[str]
    citations: list[CitationResponse] = Field(default_factory=list)
    created_at: datetime


class FeedbackCreateRequest(BaseModel):
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(ORMModel):
    id: uuid.UUID
    message_id: uuid.UUID
    user_id: uuid.UUID
    rating: FeedbackRating
    comment: str | None
    created_at: datetime
