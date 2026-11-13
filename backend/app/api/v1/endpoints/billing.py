from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.tenant import TenantContext, require_permissions
from app.db.session import get_db
from app.schemas.billing import BillingOverviewResponse, PlanChangeRequest, SubscriptionResponse
from app.services.billing_service import BillingService

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get(
    "",
    response_model=BillingOverviewResponse,
    summary="Get active subscription, plan quotas, and current period usage",
)
async def get_billing_overview(
    tenant: TenantContext = Depends(require_permissions(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_db),
) -> BillingOverviewResponse:
    svc = BillingService(db)
    sub = await svc.get_subscription(tenant.organization_id)
    usage = await svc.get_current_usage(tenant.organization_id, sub)
    return BillingOverviewResponse(
        subscription=SubscriptionResponse.model_validate(sub),
        usage=usage,
        available_plans=svc.list_available_plans(),
    )


@router.post(
    "/plan",
    response_model=SubscriptionResponse,
    summary="Switch organization subscription tier (Stripe checkout/portal placeholder)",
)
async def change_plan(
    payload: PlanChangeRequest,
    tenant: TenantContext = Depends(require_permissions(Permission.BILLING_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    sub = await BillingService(db).change_plan(tenant.organization_id, payload.plan_tier)
    return SubscriptionResponse.model_validate(sub)
