import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.security import decrypt_secret, encrypt_secret
from app.models.billing import ProviderConfig
from app.schemas.billing import ProviderConfigCreateRequest

SUPPORTED_PROVIDER_NAMES = {"openai", "azure_openai", "anthropic", "ollama", "mock"}


@dataclass(slots=True)
class ResolvedProviderCredentials:
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None


class ProviderConfigService:
    """Manages tenant-scoped encrypted AI provider API keys and endpoint overrides."""

    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    async def list_configs(self) -> list[ProviderConfig]:
        stmt = (
            select(ProviderConfig)
            .where(ProviderConfig.organization_id == self.organization_id)
            .order_by(ProviderConfig.provider_name.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def upsert_config(self, payload: ProviderConfigCreateRequest) -> ProviderConfig:
        name = payload.provider_name.strip().lower()
        if name not in SUPPORTED_PROVIDER_NAMES:
            raise AppError(
                f"Unsupported provider '{payload.provider_name}'. Supported: {', '.join(sorted(SUPPORTED_PROVIDER_NAMES))}",
                error_code="unsupported_provider",
            )

        existing = (
            await self.db.execute(
                select(ProviderConfig).where(
                    ProviderConfig.organization_id == self.organization_id,
                    ProviderConfig.provider_name == name,
                )
            )
        ).scalar_one_or_none()

        encrypted = encrypt_secret(payload.api_key)
        if existing:
            existing.encrypted_api_key = encrypted
            existing.base_url = payload.base_url
            existing.default_model = payload.default_model
            existing.is_active = True
            row = existing
        else:
            row = ProviderConfig(
                organization_id=self.organization_id,
                provider_name=name,
                encrypted_api_key=encrypted,
                base_url=payload.base_url,
                default_model=payload.default_model,
                is_active=True,
            )
            self.db.add(row)

        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete_config(self, provider_name: str) -> None:
        name = provider_name.strip().lower()
        row = (
            await self.db.execute(
                select(ProviderConfig).where(
                    ProviderConfig.organization_id == self.organization_id,
                    ProviderConfig.provider_name == name,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise NotFoundError(f"Provider configuration '{name}' not found")
        await self.db.delete(row)
        await self.db.commit()

    async def resolve_credentials(self, provider_name: str) -> ResolvedProviderCredentials:
        name = provider_name.strip().lower()
        row = (
            await self.db.execute(
                select(ProviderConfig).where(
                    ProviderConfig.organization_id == self.organization_id,
                    ProviderConfig.provider_name == name,
                    ProviderConfig.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not row:
            return ResolvedProviderCredentials()
        try:
            api_key = decrypt_secret(row.encrypted_api_key)
        except Exception:
            api_key = None
        return ResolvedProviderCredentials(
            api_key=api_key,
            base_url=row.base_url,
            default_model=row.default_model,
        )
