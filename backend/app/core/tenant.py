import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.core.logging import tenant_id_ctx, user_id_ctx
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import rate_limiter
from app.core.security import decode_jwt, hash_token
from app.db.session import apply_postgres_rls_context, get_db
from app.models.enums import OrganizationRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import APIKey, User

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class AuthenticatedPrincipal:
    user: User
    api_key: APIKey | None = None
    api_key_org_id: uuid.UUID | None = None


@dataclass(slots=True)
class TenantContext:
    organization: Organization
    organization_id: uuid.UUID
    user: User
    role: OrganizationRole
    api_key: APIKey | None = None

    def has_permission(self, permission: Permission) -> bool:
        if self.api_key and self.api_key.scopes:
            if permission.value not in self.api_key.scopes and "*" not in self.api_key.scopes:
                return False
        return has_permission(self.role, permission)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedPrincipal:
    """Authenticates via JWT Bearer token OR X-API-Key programmatic credential."""
    if x_api_key:
        hashed = hash_token(x_api_key.strip())
        stmt = select(APIKey).where(APIKey.key_hash == hashed, APIKey.is_active.is_(True))
        api_key = (await db.execute(stmt)).scalar_one_or_none()
        if not api_key or api_key.revoked_at is not None:
            raise AuthenticationError("Invalid or revoked API key", error_code="invalid_api_key")
        if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
            raise AuthenticationError("API key has expired", error_code="expired_api_key")

        user = (
            await db.execute(
                select(User).where(
                    User.id == api_key.created_by,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not user:
            raise AuthenticationError("API key owner account is inactive")

        api_key.last_used_at = datetime.now(UTC)
        api_key.request_count += 1
        await db.commit()
        user_id_ctx.set(str(user.id))
        return AuthenticatedPrincipal(
            user=user,
            api_key=api_key,
            api_key_org_id=api_key.organization_id,
        )

    if not credentials or not credentials.credentials:
        raise AuthenticationError("Missing authentication credentials", error_code="missing_credentials")

    payload = decode_jwt(credentials.credentials, expected_type="access")
    try:
        user_uuid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Malformed token subject") from exc

    user = (
        await db.execute(
            select(User).where(
                User.id == user_uuid,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not user:
        raise AuthenticationError("User not found or deactivated")

    user_id_ctx.set(str(user.id))
    return AuthenticatedPrincipal(user=user)


async def get_current_user(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> User:
    return principal.user


async def get_current_tenant(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """
    Strictly resolves the active organization from:
      1) API key's bound organization_id (cannot be overridden by headers), OR
      2) X-Organization-ID header, OR
      3) Subdomain slug (e.g., acme.knowledgeforge.ai), OR
      4) Path parameter organization_id if present.
    NEVER trusts organization_id from request JSON body.
    Verifies active membership in OrganizationMember before granting access.
    """
    resolved_org_id: uuid.UUID | None = None
    resolved_slug: str | None = None

    if principal.api_key_org_id is not None:
        if x_organization_id and x_organization_id != str(principal.api_key_org_id):
            raise AuthorizationError("API key is scoped to a different organization")
        resolved_org_id = principal.api_key_org_id
    elif x_organization_id:
        try:
            resolved_org_id = uuid.UUID(x_organization_id)
        except ValueError as exc:
            raise AuthorizationError("Invalid X-Organization-ID header format") from exc
    elif "organization_id" in request.path_params:
        try:
            resolved_org_id = uuid.UUID(str(request.path_params["organization_id"]))
        except ValueError as exc:
            raise AuthorizationError("Invalid organization_id path parameter") from exc
    else:
        host = request.headers.get("host", "").split(":")[0]
        parts = host.split(".")
        if len(parts) >= 3 and parts[0] not in {"www", "api", "app"}:
            resolved_slug = parts[0]

    if resolved_org_id is not None:
        org_stmt = select(Organization).where(
            Organization.id == resolved_org_id,
            Organization.deleted_at.is_(None),
        )
    elif resolved_slug is not None:
        org_stmt = select(Organization).where(
            Organization.slug == resolved_slug,
            Organization.deleted_at.is_(None),
        )
    else:
        raise AuthorizationError(
            "Organization context required. Provide X-Organization-ID header.",
            error_code="tenant_context_required",
        )

    org = (await db.execute(org_stmt)).scalar_one_or_none()
    if not org:
        raise NotFoundError("Organization not found", error_code="organization_not_found")

    membership = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.user_id == principal.user.id,
            )
        )
    ).scalar_one_or_none()

    if not membership:
        raise AuthorizationError(
            "User is not a member of the requested organization",
            error_code="tenant_access_denied",
        )

    tenant_id_ctx.set(str(org.id))
    await apply_postgres_rls_context(db, org.id)
    await rate_limiter.check_rate_limit(
        f"org:{org.id}",
        limit=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
    )

    return TenantContext(
        organization=org,
        organization_id=org.id,
        user=principal.user,
        role=membership.role,
        api_key=principal.api_key,
    )


def require_permissions(*required: Permission):
    """FastAPI dependency factory verifying RBAC permissions on the resolved TenantContext."""

    async def _dependency(tenant: TenantContext = Depends(get_current_tenant)) -> TenantContext:
        for perm in required:
            if not tenant.has_permission(perm):
                raise AuthorizationError(
                    f"Missing required permission: {perm.value}",
                    error_code="insufficient_permissions",
                )
        return tenant

    return _dependency
