import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.models.enums import PlanTier, SubscriptionStatus


class Subscription(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_subscription_org"),
    )

    plan_tier: Mapped[PlanTier] = mapped_column(
        SAEnum(PlanTier, name="plan_tier", native_enum=False),
        default=PlanTier.FREE,
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, name="subscription_status", native_enum=False),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    monthly_document_limit: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=100 * 1024 * 1024, nullable=False)
    monthly_ai_request_limit: Mapped[int] = mapped_column(Integer, default=250, nullable=False)
    monthly_token_limit: Mapped[int] = mapped_column(BigInteger, default=250_000, nullable=False)
    team_member_limit: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    knowledge_base_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsageRecord(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_org_metric_created", "organization_id", "metric_type", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ProviderConfig(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "provider_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_name", name="uq_provider_config_org_name"),
    )

    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class WebhookEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="uq_webhook_provider_event_id"),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
