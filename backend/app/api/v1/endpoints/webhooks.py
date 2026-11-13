import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.db.session import get_db
from app.services.billing_service import BillingService

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_stripe_signature(raw_body: bytes, signature_header: str | None, secret: str, tolerance_seconds: int = 300) -> None:
    if not signature_header:
        raise AuthenticationError("Missing Stripe-Signature header", error_code="invalid_webhook_signature")

    timestamp: str | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "t":
            timestamp = v
        elif k == "v1":
            signatures.append(v)

    if not timestamp or not signatures:
        raise AuthenticationError("Malformed Stripe-Signature header", error_code="invalid_webhook_signature")

    try:
        ts_int = int(timestamp)
    except ValueError as exc:
        raise AuthenticationError("Invalid Stripe signature timestamp", error_code="invalid_webhook_signature") from exc

    if abs(int(time.time()) - ts_int) > tolerance_seconds:
        raise AuthenticationError("Expired Stripe webhook timestamp", error_code="invalid_webhook_signature")

    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    expected_sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected_sig, sig) for sig in signatures):
        raise AuthenticationError("Invalid Stripe webhook signature", error_code="invalid_webhook_signature")


@router.post("/stripe", summary="Idempotent Stripe billing webhook receiver")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    if settings.STRIPE_WEBHOOK_SECRET:
        verify_stripe_signature(raw_body, stripe_signature, settings.STRIPE_WEBHOOK_SECRET)
    elif settings.is_production:
        raise AuthenticationError("Stripe webhook secret is not configured", error_code="webhook_unconfigured")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise AuthenticationError("Invalid webhook JSON payload") from exc

    event_id = str(payload.get("id") or idempotency_key or "")
    if not event_id:
        raise AuthenticationError("Missing webhook event identifier")
    event_type = str(payload.get("type") or "unknown")

    duplicate, event = await BillingService(db).process_stripe_webhook(
        external_event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    return {"received": True, "duplicate": duplicate, "event_id": event.external_event_id}
