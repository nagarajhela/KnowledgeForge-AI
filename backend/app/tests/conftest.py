import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["APP_ENV"] = "test"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["DEFAULT_LLM_PROVIDER"] = "mock"
os.environ["DEFAULT_EMBEDDING_PROVIDER"] = "mock"

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncGenerator[AsyncSession, None]:
    settings.APP_ENV = "test"
    settings.STORAGE_BACKEND = "local"
    settings.LOCAL_STORAGE_PATH = str(tmp_path / "storage")
    settings.RATE_LIMIT_ENABLED = True
    rate_limiter._local_buckets.clear()

    db_file = tmp_path / "test_kf.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def register_user_and_org(
    client: AsyncClient,
    *,
    email: str,
    password: str = "StrongPass123!",
    full_name: str = "Test User",
    org_name: str = "Acme Corp",
) -> dict:
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": full_name,
            "organization_name": org_name,
        },
    )
    assert reg.status_code == 201, reg.text
    tokens = reg.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    orgs_resp = await client.get("/api/v1/organizations", headers=headers)
    assert orgs_resp.status_code == 200
    org = orgs_resp.json()[0]
    return {
        "user": tokens["user"],
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "organization_id": org["id"],
        "headers": {
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Organization-ID": org["id"],
        },
    }
