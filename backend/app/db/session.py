import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def build_async_engine(database_url: str | None = None) -> AsyncEngine:
    url = database_url or settings.DATABASE_URL
    kwargs: dict[str, object] = {"echo": settings.DEBUG, "pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    return create_async_engine(url, **kwargs)


engine = build_async_engine()
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def apply_postgres_rls_context(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Sets transaction-local PostgreSQL session variable for Row-Level Security policies."""
    if not settings.ENABLE_POSTGRES_RLS:
        return
    dialect_name = session.bind.dialect.name if session.bind else ""
    if dialect_name == "postgresql":
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :org_id, true)"),
            {"org_id": str(organization_id)},
        )
