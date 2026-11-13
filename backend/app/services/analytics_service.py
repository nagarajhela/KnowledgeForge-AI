import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import UsageRecord
from app.models.chat import ChatMessage
from app.models.enums import IngestionJobStatus, MessageRole
from app.models.knowledge import Document, DocumentChunk, IngestionJob
from app.models.user import APIKey
from app.schemas.billing import AnalyticsOverviewResponse


class AnalyticsService:
    """Tenant-scoped administration and usage analytics."""

    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    async def get_overview(self) -> AnalyticsOverviewResponse:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now - timedelta(days=30)

        total_documents = int(
            (
                await self.db.execute(
                    select(func.count(Document.id)).where(
                        Document.organization_id == self.organization_id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        total_chunks = int(
            (
                await self.db.execute(
                    select(func.count(DocumentChunk.id)).where(
                        DocumentChunk.organization_id == self.organization_id
                    )
                )
            ).scalar_one()
        )
        storage_used_bytes = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(Document.file_size_bytes), 0)).where(
                        Document.organization_id == self.organization_id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        ai_requests_today = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                        UsageRecord.organization_id == self.organization_id,
                        UsageRecord.metric_type == "ai_request",
                        UsageRecord.created_at >= day_start,
                    )
                )
            ).scalar_one()
        )
        ai_requests_month = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                        UsageRecord.organization_id == self.organization_id,
                        UsageRecord.metric_type == "ai_request",
                        UsageRecord.created_at >= month_start,
                    )
                )
            ).scalar_one()
        )
        tokens_used_month = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                        UsageRecord.organization_id == self.organization_id,
                        UsageRecord.metric_type == "tokens",
                        UsageRecord.created_at >= month_start,
                    )
                )
            ).scalar_one()
        )
        active_users = int(
            (
                await self.db.execute(
                    select(func.count(func.distinct(UsageRecord.user_id))).where(
                        UsageRecord.organization_id == self.organization_id,
                        UsageRecord.user_id.is_not(None),
                        UsageRecord.created_at >= month_start,
                    )
                )
            ).scalar_one()
        )
        failed_ingestion_jobs = int(
            (
                await self.db.execute(
                    select(func.count(IngestionJob.id)).where(
                        IngestionJob.organization_id == self.organization_id,
                        IngestionJob.status == IngestionJobStatus.FAILED,
                    )
                )
            ).scalar_one()
        )

        status_rows = (
            await self.db.execute(
                select(Document.processing_status, func.count(Document.id))
                .where(
                    Document.organization_id == self.organization_id,
                    Document.deleted_at.is_(None),
                )
                .group_by(Document.processing_status)
            )
        ).all()
        document_status_breakdown = {str(status.value): int(cnt) for status, cnt in status_rows}

        cost_rows = (
            await self.db.execute(
                select(
                    UsageRecord.provider,
                    UsageRecord.model,
                    func.coalesce(func.sum(UsageRecord.quantity), 0),
                    func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0.0),
                )
                .where(
                    UsageRecord.organization_id == self.organization_id,
                    UsageRecord.metric_type == "tokens",
                    UsageRecord.created_at >= month_start,
                )
                .group_by(UsageRecord.provider, UsageRecord.model)
            )
        ).all()
        cost_by_provider_model = [
            {
                "provider": provider or "default",
                "model": model or "unknown",
                "tokens": int(tokens),
                "estimated_cost_usd": round(float(cost), 4),
            }
            for provider, model, tokens, cost in cost_rows
        ]

        question_rows = (
            await self.db.execute(
                select(ChatMessage.content, func.count(ChatMessage.id).label("cnt"))
                .where(
                    ChatMessage.organization_id == self.organization_id,
                    ChatMessage.role == MessageRole.USER,
                )
                .group_by(ChatMessage.content)
                .order_by(func.count(ChatMessage.id).desc())
                .limit(10)
            )
        ).all()
        most_asked_questions = [
            {"question": q[:200], "count": int(cnt)} for q, cnt in question_rows
        ]

        key_rows = (
            await self.db.execute(
                select(APIKey.id, APIKey.name, APIKey.key_prefix, APIKey.request_count, APIKey.last_used_at)
                .where(APIKey.organization_id == self.organization_id)
                .order_by(APIKey.request_count.desc())
            )
        ).all()
        api_key_usage = [
            {
                "id": str(k_id),
                "name": name,
                "key_prefix": prefix,
                "request_count": int(req_count),
                "last_used_at": last_used.isoformat() if last_used else None,
            }
            for k_id, name, prefix, req_count, last_used in key_rows
        ]

        return AnalyticsOverviewResponse(
            total_documents=total_documents,
            total_chunks=total_chunks,
            storage_used_bytes=storage_used_bytes,
            ai_requests_today=ai_requests_today,
            ai_requests_month=ai_requests_month,
            tokens_used_month=tokens_used_month,
            active_users=active_users,
            failed_ingestion_jobs=failed_ingestion_jobs,
            document_status_breakdown=document_status_breakdown,
            cost_by_provider_model=cost_by_provider_model,
            most_asked_questions=most_asked_questions,
            api_key_usage=api_key_usage,
        )
