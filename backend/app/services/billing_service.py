import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, QuotaExceededError
from app.models.billing import Subscription, UsageRecord, WebhookEvent
from app.models.enums import PlanTier, SubscriptionStatus
from app.models.knowledge import Document, KnowledgeBase
from app.models.organization import OrganizationMember


@dataclass(frozen=True, slots=True)
class PlanSpec:
    tier: PlanTier
    name: str
    monthly_price_usd: int
    monthly_document_limit: int
    storage_limit_bytes: int
    monthly_ai_request_limit: int
    monthly_token_limit: int
    team_member_limit: int
    knowledge_base_limit: int


PLAN_CATALOG: dict[PlanTier, PlanSpec] = {
    PlanTier.FREE: PlanSpec(
        tier=PlanTier.FREE,
        name="Free",
        monthly_price_usd=0,
        monthly_document_limit=25,
        storage_limit_bytes=100 * 1024 * 1024,
        monthly_ai_request_limit=250,
        monthly_token_limit=250_000,
        team_member_limit=5,
        knowledge_base_limit=3,
    ),
    PlanTier.STARTER: PlanSpec(
        tier=PlanTier.STARTER,
        name="Starter",
        monthly_price_usd=49,
        monthly_document_limit=250,
        storage_limit_bytes=2 * 1024 * 1024 * 1024,
        monthly_ai_request_limit=5_000,
        monthly_token_limit=5_000_000,
        team_member_limit=20,
        knowledge_base_limit=15,
    ),
    PlanTier.PRO: PlanSpec(
        tier=PlanTier.PRO,
        name="Pro",
        monthly_price_usd=199,
        monthly_document_limit=2_500,
        storage_limit_bytes=25 * 1024 * 1024 * 1024,
        monthly_ai_request_limit=50_000,
        monthly_token_limit=50_000_000,
        team_member_limit=100,
        knowledge_base_limit=100,
    ),
    PlanTier.ENTERPRISE: PlanSpec(
        tier=PlanTier.ENTERPRISE,
        name="Enterprise",
        monthly_price_usd=799,
        monthly_document_limit=100_000,
        storage_limit_bytes=500 * 1024 * 1024 * 1024,
        monthly_ai_request_limit=1_000_000,
        monthly_token_limit=1_000_000_000,
        team_member_limit=5_000,
        knowledge_base_limit=2_000,
    ),
}


class BillingService:
    """Manages tenant subscriptions, usage metering, Stripe checkout placeholders, and quota checks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_default_subscription(self, organization_id: uuid.UUID) -> Subscription:
        spec = PLAN_CATALOG[PlanTier.FREE]
        now = datetime.now(UTC)
        sub = Subscription(
            organization_id=organization_id,
            plan_tier=spec.tier,
            status=SubscriptionStatus.ACTIVE,
            monthly_document_limit=spec.monthly_document_limit,
            storage_limit_bytes=spec.storage_limit_bytes,
            monthly_ai_request_limit=spec.monthly_ai_request_limit,
            monthly_token_limit=spec.monthly_token_limit,
            team_member_limit=spec.team_member_limit,
            knowledge_base_limit=spec.knowledge_base_limit,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        self.db.add(sub)
        await self.db.flush()
        return sub

    async def get_subscription(self, organization_id: uuid.UUID) -> Subscription:
        sub = (
            await self.db.execute(
                select(Subscription).where(Subscription.organization_id == organization_id)
            )
        ).scalar_one_or_none()
        if not sub:
            sub = await self.create_default_subscription(organization_id)
            await self.db.commit()
        return sub

    async def get_current_usage(self, organization_id: uuid.UUID, sub: Subscription) -> dict[str, int]:
        doc_count = int(
            (
                await self.db.execute(
                    select(func.count(Document.id)).where(
                        Document.organization_id == organization_id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        storage_bytes = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(Document.file_size_bytes), 0)).where(
                        Document.organization_id == organization_id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        kb_count = int(
            (
                await self.db.execute(
                    select(func.count(KnowledgeBase.id)).where(
                        KnowledgeBase.organization_id == organization_id,
                        KnowledgeBase.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        member_count = int(
            (
                await self.db.execute(
                    select(func.count(OrganizationMember.id)).where(
                        OrganizationMember.organization_id == organization_id,
                    )
                )
            ).scalar_one()
        )
        ai_requests = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                        UsageRecord.organization_id == organization_id,
                        UsageRecord.metric_type == "ai_request",
                        UsageRecord.created_at >= sub.current_period_start,
                    )
                )
            ).scalar_one()
        )
        tokens = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                        UsageRecord.organization_id == organization_id,
                        UsageRecord.metric_type == "tokens",
                        UsageRecord.created_at >= sub.current_period_start,
                    )
                )
            ).scalar_one()
        )
        return {
            "documents": doc_count,
            "storage_bytes": storage_bytes,
            "knowledge_bases": kb_count,
            "team_members": member_count,
            "ai_requests": ai_requests,
            "tokens": tokens,
        }

    async def assert_can_create_kb(self, organization_id: uuid.UUID) -> None:
        sub = await self.get_subscription(organization_id)
        usage = await self.get_current_usage(organization_id, sub)
        if usage["knowledge_bases"] >= sub.knowledge_base_limit:
            raise QuotaExceededError(
                "Knowledge base limit reached for current plan.",
                details={"limit": sub.knowledge_base_limit, "current": usage["knowledge_bases"]},
            )

    async def assert_can_upload_document(
        self, organization_id: uuid.UUID, incoming_bytes: int = 0
    ) -> None:
        sub = await self.get_subscription(organization_id)
        usage = await self.get_current_usage(organization_id, sub)
        if usage["documents"] >= sub.monthly_document_limit:
            raise QuotaExceededError(
                "Document limit reached for current plan.",
                details={"limit": sub.monthly_document_limit, "current": usage["documents"]},
            )
        if usage["storage_bytes"] + incoming_bytes > sub.storage_limit_bytes:
            raise QuotaExceededError(
                "Storage limit exceeded for current plan.",
                details={"limit_bytes": sub.storage_limit_bytes, "current_bytes": usage["storage_bytes"]},
            )

    async def assert_can_invite_member(self, organization_id: uuid.UUID) -> None:
        sub = await self.get_subscription(organization_id)
        usage = await self.get_current_usage(organization_id, sub)
        if usage["team_members"] >= sub.team_member_limit:
            raise QuotaExceededError(
                "Team member limit reached for current plan.",
                details={"limit": sub.team_member_limit, "current": usage["team_members"]},
            )

    async def assert_can_run_chat(self, organization_id: uuid.UUID) -> None:
        sub = await self.get_subscription(organization_id)
        usage = await self.get_current_usage(organization_id, sub)
        if usage["ai_requests"] >= sub.monthly_ai_request_limit:
            raise QuotaExceededError(
                "Monthly AI request quota exceeded.",
                details={"limit": sub.monthly_ai_request_limit, "current": usage["ai_requests"]},
            )
        if usage["tokens"] >= sub.monthly_token_limit:
            raise QuotaExceededError(
                "Monthly token quota exceeded.",
                details={"limit": sub.monthly_token_limit, "current": usage["tokens"]},
            )

    async def record_usage(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        metric_type: str,
        quantity: int,
        provider: str | None = None,
        model: str | None = None,
        estimated_cost_usd: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        record = UsageRecord(
            organization_id=organization_id,
            user_id=user_id,
            metric_type=metric_type,
            quantity=quantity,
            provider=provider,
            model=model,
            estimated_cost_usd=estimated_cost_usd,
            metadata_json=metadata or {},
        )
        self.db.add(record)

    async def change_plan(self, organization_id: uuid.UUID, plan_tier: PlanTier) -> Subscription:
        spec = PLAN_CATALOG[plan_tier]
        sub = await self.get_subscription(organization_id)
        sub.plan_tier = spec.tier
        sub.status = SubscriptionStatus.ACTIVE
        sub.monthly_document_limit = spec.monthly_document_limit
        sub.storage_limit_bytes = spec.storage_limit_bytes
        sub.monthly_ai_request_limit = spec.monthly_ai_request_limit
        sub.monthly_token_limit = spec.monthly_token_limit
        sub.team_member_limit = spec.team_member_limit
        sub.knowledge_base_limit = spec.knowledge_base_limit
        await self.db.commit()
        await self.db.refresh(sub)
        return sub

    async def process_stripe_webhook(
        self, *, external_event_id: str, event_type: str, payload: dict
    ) -> tuple[bool, WebhookEvent]:
        """Idempotent Stripe webhook handler."""
        existing = (
            await self.db.execute(
                select(WebhookEvent).where(
                    WebhookEvent.provider == "stripe",
                    WebhookEvent.external_event_id == external_event_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return True, existing

        org_id_raw = payload.get("data", {}).get("object", {}).get("metadata", {}).get("organization_id")
        org_id = uuid.UUID(org_id_raw) if org_id_raw else None
        event = WebhookEvent(
            provider="stripe",
            external_event_id=external_event_id,
            event_type=event_type,
            organization_id=org_id,
            payload_json=payload,
            processed_at=datetime.now(UTC),
        )
        self.db.add(event)

        if org_id and event_type == "customer.subscription.deleted":
            sub = (
                await self.db.execute(select(Subscription).where(Subscription.organization_id == org_id))
            ).scalar_one_or_none()
            if sub:
                sub.status = SubscriptionStatus.CANCELED
        await self.db.commit()
        return False, event

    @staticmethod
    def list_available_plans() -> list[dict]:
        return [
            {
                "tier": s.tier.value,
                "name": s.name,
                "monthly_price_usd": s.monthly_price_usd,
                "monthly_document_limit": s.monthly_document_limit,
                "storage_limit_mb": s.storage_limit_bytes // (1024 * 1024),
                "monthly_ai_request_limit": s.monthly_ai_request_limit,
                "monthly_token_limit": s.monthly_token_limit,
                "team_member_limit": s.team_member_limit,
                "knowledge_base_limit": s.knowledge_base_limit,
            }
            for s in PLAN_CATALOG.values()
        ]
