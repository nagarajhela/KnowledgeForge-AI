import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import generate_api_key
from app.models.user import APIKey
from app.schemas.billing import APIKeyCreateRequest, APIKeyCreatedResponse
from app.services.organization_service import OrganizationService


class APIKeyService:
    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    async def create_key(
        self, user_id: uuid.UUID, payload: APIKeyCreateRequest
    ) -> APIKeyCreatedResponse:
        plaintext, prefix, key_hash = generate_api_key()
        expires_at = (
            datetime.now(UTC) + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days
            else None
        )
        key = APIKey(
            organization_id=self.organization_id,
            created_by=user_id,
            name=payload.name.strip(),
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=payload.scopes,
            is_active=True,
            expires_at=expires_at,
        )
        self.db.add(key)
        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="api_key.created",
            resource_type="api_key",
            metadata={"name": key.name, "prefix": prefix},
        )
        await self.db.commit()
        await self.db.refresh(key)
        return APIKeyCreatedResponse(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            scopes=key.scopes,
            is_active=key.is_active,
            last_used_at=key.last_used_at,
            request_count=key.request_count,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
            created_at=key.created_at,
            plaintext_key=plaintext,
        )

    async def list_keys(self) -> list[APIKey]:
        stmt = (
            select(APIKey)
            .where(APIKey.organization_id == self.organization_id)
            .order_by(APIKey.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def revoke_key(self, key_id: uuid.UUID, actor_user_id: uuid.UUID) -> APIKey:
        key = (
            await self.db.execute(
                select(APIKey).where(
                    APIKey.id == key_id,
                    APIKey.organization_id == self.organization_id,
                )
            )
        ).scalar_one_or_none()
        if not key:
            raise NotFoundError("API key not found")
        key.is_active = False
        key.revoked_at = datetime.now(UTC)
        await OrganizationService(self.db).record_audit_log(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="api_key.revoked",
            resource_type="api_key",
            resource_id=str(key.id),
        )
        await self.db.commit()
        await self.db.refresh(key)
        return key
