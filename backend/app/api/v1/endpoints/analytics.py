from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.billing import AnalyticsOverviewResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get(
    "/overview",
    response_model=AnalyticsOverviewResponse,
    summary="Get organization-wide documents, chunks, storage, token, and cost analytics",
)
async def get_analytics_overview(
    tenant: TenantContext = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverviewResponse:
    return await AnalyticsService(db, tenant.organization_id).get_overview()
