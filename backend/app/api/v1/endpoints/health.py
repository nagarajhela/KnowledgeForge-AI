import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.schemas.common import HealthComponent, HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and readiness check")
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    components: dict[str, HealthComponent] = {}
    overall = "ok"

    try:
        await db.execute(text("SELECT 1"))
        components["database"] = HealthComponent(status="ok")
    except Exception as exc:
        overall = "degraded"
        components["database"] = HealthComponent(status="error", detail=type(exc).__name__)

    if settings.APP_ENV == "test":
        components["redis"] = HealthComponent(status="skipped", detail="test mode")
    else:
        try:
            client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1.5)
            await client.ping()
            await client.aclose()
            components["redis"] = HealthComponent(status="ok")
        except Exception as exc:
            components["redis"] = HealthComponent(status="degraded", detail=type(exc).__name__)

    components["storage"] = HealthComponent(status="ok", detail=settings.STORAGE_BACKEND)

    return HealthResponse(
        status=overall,
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        components=components,
    )
