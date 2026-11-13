import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import PlanTier, SubscriptionStatus
from app.schemas.common import ORMModel


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["kb:read", "chat:ask"])
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class APIKeyResponse(ORMModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    last_used_at: datetime | None
    request_count: int
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class APIKeyCreatedResponse(APIKeyResponse):
    plaintext_key: str = Field(description="Shown only once at creation time.")


class SubscriptionResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    plan_tier: PlanTier
    status: SubscriptionStatus
    monthly_document_limit: int
    storage_limit_bytes: int
    monthly_ai_request_limit: int
    monthly_token_limit: int
    team_member_limit: int
    knowledge_base_limit: int
    current_period_start: datetime
    current_period_end: datetime


class PlanChangeRequest(BaseModel):
    plan_tier: PlanTier


class BillingOverviewResponse(BaseModel):
    subscription: SubscriptionResponse
    usage: dict[str, int]
    available_plans: list[dict]


class ProviderConfigCreateRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1)
    base_url: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=120)


class ProviderConfigResponse(ORMModel):
    id: uuid.UUID
    provider_name: str
    base_url: str | None
    default_model: str | None
    is_active: bool
    created_at: datetime


class AnalyticsOverviewResponse(BaseModel):
    total_documents: int
    total_chunks: int
    storage_used_bytes: int
    ai_requests_today: int
    ai_requests_month: int
    tokens_used_month: int
    active_users: int
    failed_ingestion_jobs: int
    document_status_breakdown: dict[str, int]
    cost_by_provider_model: list[dict]
    most_asked_questions: list[dict]
    api_key_usage: list[dict]
