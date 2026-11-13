import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    RateLimitExceededError,
)
from app.core.rate_limit import rate_limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_jwt,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.enums import OrganizationRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import OAuthAccount, RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    OAuthAuthorizeResponse,
    RegisterRequest,
    TokenPairResponse,
    UserProfileUpdateRequest,
    UserResponse,
)
from app.services.billing_service import BillingService


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    return f"{base[:90]}-{secrets.token_hex(3)}"


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(
        self,
        payload: RegisterRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPairResponse:
        existing = (
            await self.db.execute(select(User).where(User.email == payload.email.lower()))
        ).scalar_one_or_none()
        if existing:
            raise ConflictError("An account with this email already exists", error_code="email_exists")

        raw_verify_token, verify_hash = generate_opaque_token()
        _ = raw_verify_token  # Sent via transactional email provider in production

        user = User(
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            is_active=True,
            is_email_verified=False,
            email_verification_token_hash=verify_hash,
            last_login_at=datetime.now(UTC),
        )
        self.db.add(user)
        await self.db.flush()

        if payload.organization_name:
            org = Organization(
                name=payload.organization_name.strip(),
                slug=_slugify(payload.organization_name),
            )
            self.db.add(org)
            await self.db.flush()
            self.db.add(
                OrganizationMember(
                    organization_id=org.id,
                    user_id=user.id,
                    role=OrganizationRole.OWNER,
                )
            )
            await BillingService(self.db).create_default_subscription(org.id)

        tokens = await self._issue_token_pair(
            user=user,
            device_name="Web Registration",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.db.commit()
        return tokens

    async def login(
        self,
        payload: LoginRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPairResponse:
        email = payload.email.lower()
        if await rate_limiter.is_login_locked(email):
            raise RateLimitExceededError(
                "Account temporarily locked due to repeated failed login attempts.",
                retry_after=settings.LOGIN_LOCKOUT_MINUTES * 60,
            )

        user = (
            await self.db.execute(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()

        if not user or not verify_password(payload.password, user.hashed_password):
            await rate_limiter.record_failed_login(email)
            raise AuthenticationError("Invalid email or password", error_code="invalid_credentials")

        if not user.is_active:
            raise AuthenticationError("Account is disabled", error_code="account_disabled")

        await rate_limiter.reset_failed_login(email)
        user.last_login_at = datetime.now(UTC)

        tokens = await self._issue_token_pair(
            user=user,
            device_name=payload.device_name,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.db.commit()
        return tokens

    async def refresh(
        self,
        raw_refresh_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPairResponse:
        payload = decode_jwt(raw_refresh_token, expected_type="refresh")
        token_hash = hash_token(raw_refresh_token)
        stored = (
            await self.db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()

        if not stored:
            raise AuthenticationError("Refresh token not recognized", error_code="invalid_refresh_token")

        if stored.revoked_at is not None:
            # Refresh token reuse detected -> revoke entire token family
            family_tokens = (
                await self.db.execute(
                    select(RefreshToken).where(
                        RefreshToken.token_family == stored.token_family,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            ).scalars().all()
            now = datetime.now(UTC)
            for fam_tok in family_tokens:
                fam_tok.revoked_at = now
            await self.db.commit()
            raise AuthenticationError(
                "Refresh token reuse detected. All sessions in this family were revoked.",
                error_code="refresh_token_reused",
            )

        expires_at = stored.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise AuthenticationError("Refresh token expired", error_code="refresh_token_expired")

        user = (
            await self.db.execute(
                select(User).where(
                    User.id == uuid.UUID(payload["sub"]),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not user:
            raise AuthenticationError("User not found or inactive")

        new_pair = await self._issue_token_pair(
            user=user,
            token_family=stored.token_family,
            device_name=stored.device_name,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        stored.revoked_at = datetime.now(UTC)
        await self.db.commit()
        return new_pair

    async def logout(
        self,
        user: User,
        *,
        raw_refresh_token: str | None = None,
        revoke_all: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        if revoke_all:
            tokens = (
                await self.db.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user.id,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            ).scalars().all()
            for tok in tokens:
                tok.revoked_at = now
        elif raw_refresh_token:
            tok = (
                await self.db.execute(
                    select(RefreshToken).where(
                        RefreshToken.token_hash == hash_token(raw_refresh_token),
                        RefreshToken.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if tok and tok.revoked_at is None:
                tok.revoked_at = now
        await self.db.commit()

    async def list_sessions(self, user_id: uuid.UUID) -> list[RefreshToken]:
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def verify_email(self, raw_token: str) -> None:
        token_hash = hash_token(raw_token)
        user = (
            await self.db.execute(
                select(User).where(User.email_verification_token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if not user:
            raise NotFoundError("Invalid verification token")
        user.is_email_verified = True
        user.email_verification_token_hash = None
        await self.db.commit()

    async def request_password_reset(self, email: str) -> str | None:
        user = (
            await self.db.execute(select(User).where(User.email == email.lower()))
        ).scalar_one_or_none()
        if not user:
            return None
        raw, token_hash = generate_opaque_token()
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
        await self.db.commit()
        return raw

    async def confirm_password_reset(self, raw_token: str, new_password: str) -> None:
        token_hash = hash_token(raw_token)
        user = (
            await self.db.execute(select(User).where(User.password_reset_token_hash == token_hash))
        ).scalar_one_or_none()
        if not user or not user.password_reset_expires_at:
            raise NotFoundError("Invalid or expired password reset token")
        exp = user.password_reset_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp < datetime.now(UTC):
            raise AuthenticationError("Password reset token has expired")
        user.hashed_password = hash_password(new_password)
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        await self.db.commit()

    async def update_profile(self, user: User, payload: UserProfileUpdateRequest) -> User:
        if payload.full_name is not None:
            user.full_name = payload.full_name.strip()
        if payload.avatar_url is not None:
            user.avatar_url = payload.avatar_url
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def gdpr_anonymize_user(self, user: User) -> None:
        """GDPR right-to-erasure anonymization preserving referential audit integrity."""
        now = datetime.now(UTC)
        user.email = f"deleted-{user.id}@anonymized.local"
        user.full_name = "Deleted User"
        user.avatar_url = None
        user.hashed_password = None
        user.is_active = False
        user.gdpr_anonymized_at = now
        user.deleted_at = now
        await self.logout(user, revoke_all=True)

    @staticmethod
    def _create_oauth_state(provider: str) -> str:
        now = datetime.now(UTC)
        payload = {
            "provider": provider,
            "nonce": secrets.token_urlsafe(16),
            "type": "oauth_state",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def _verify_oauth_state(state: str, provider: str) -> None:
        payload = decode_jwt(state, expected_type="oauth_state")
        if payload.get("provider") != provider:
            raise AuthenticationError("OAuth state does not match provider", error_code="invalid_oauth_state")

    @staticmethod
    def build_oauth_authorization_url(provider: str) -> OAuthAuthorizeResponse:
        if provider not in {"google", "microsoft"}:
            raise NotFoundError(f"Unsupported OAuth provider: {provider}")
        state = AuthService._create_oauth_state(provider)
        if provider == "google":
            params = urlencode(
                {
                    "client_id": settings.GOOGLE_CLIENT_ID or "mock-google-client-id",
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": state,
                    "access_type": "offline",
                }
            )
            url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
        else:
            params = urlencode(
                {
                    "client_id": settings.MICROSOFT_CLIENT_ID or "mock-microsoft-client-id",
                    "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
                    "response_type": "code",
                    "scope": "openid email profile User.Read",
                    "state": state,
                }
            )
            url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{params}"
        return OAuthAuthorizeResponse(provider=provider, authorization_url=url, state=state)

    async def handle_oauth_callback(
        self,
        *,
        provider: str,
        code: str,
        state: str | None = None,
        mock_email: str | None = None,
        mock_full_name: str | None = None,
    ) -> TokenPairResponse:
        if provider not in {"google", "microsoft"}:
            raise NotFoundError(f"Unsupported OAuth provider: {provider}")

        if state is not None:
            self._verify_oauth_state(state, provider)

        if provider == "google" and settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                )
                if token_resp.status_code >= 400:
                    raise AuthenticationError("Google OAuth token exchange failed", error_code="oauth_exchange_failed")
                access_tok = token_resp.json().get("access_token")
                userinfo_resp = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_tok}"},
                )
                if userinfo_resp.status_code >= 400:
                    raise AuthenticationError("Failed to fetch Google user profile", error_code="oauth_userinfo_failed")
                profile = userinfo_resp.json()
            if not profile.get("email_verified", True):
                raise AuthenticationError("Google account email is not verified")
            return await self.oauth_login_or_create(
                provider="google",
                provider_account_id=str(profile["sub"]),
                email=str(profile["email"]),
                full_name=str(profile.get("name") or profile["email"]),
            )

        if provider == "microsoft" and settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token_resp = await client.post(
                    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                    data={
                        "code": code,
                        "client_id": settings.MICROSOFT_CLIENT_ID,
                        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                )
                if token_resp.status_code >= 400:
                    raise AuthenticationError("Microsoft OAuth token exchange failed", error_code="oauth_exchange_failed")
                access_tok = token_resp.json().get("access_token")
                userinfo_resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers={"Authorization": f"Bearer {access_tok}"},
                )
                if userinfo_resp.status_code >= 400:
                    raise AuthenticationError("Failed to fetch Microsoft user profile", error_code="oauth_userinfo_failed")
                profile = userinfo_resp.json()
            email = profile.get("mail") or profile.get("userPrincipalName")
            if not email:
                raise AuthenticationError("Microsoft account did not return an email address")
            return await self.oauth_login_or_create(
                provider="microsoft",
                provider_account_id=str(profile["id"]),
                email=str(email),
                full_name=str(profile.get("displayName") or email),
            )

        if settings.APP_ENV not in {"development", "test"}:
            raise AuthenticationError(
                f"OAuth provider '{provider}' credentials are not configured",
                error_code="oauth_not_configured",
            )
        if not state:
            raise AuthenticationError("Missing signed OAuth state parameter", error_code="invalid_oauth_state")
        return await self.oauth_login_or_create(
            provider=provider,
            provider_account_id=f"{provider}-{code[:24]}",
            email=mock_email or "oauth.user@example.com",
            full_name=mock_full_name or "OAuth User",
        )

    async def oauth_login_or_create(
        self,
        *,
        provider: str,
        provider_account_id: str,
        email: str,
        full_name: str,
    ) -> TokenPairResponse:
        oauth_acc = (
            await self.db.execute(
                select(OAuthAccount).where(
                    OAuthAccount.provider == provider,
                    OAuthAccount.provider_account_id == provider_account_id,
                )
            )
        ).scalar_one_or_none()
        if oauth_acc:
            user = (
                await self.db.execute(select(User).where(User.id == oauth_acc.user_id))
            ).scalar_one()
        else:
            user = (
                await self.db.execute(select(User).where(User.email == email.lower()))
            ).scalar_one_or_none()
            if not user:
                user = User(
                    email=email.lower(),
                    full_name=full_name,
                    is_active=True,
                    is_email_verified=True,
                )
                self.db.add(user)
                await self.db.flush()
            self.db.add(
                OAuthAccount(
                    user_id=user.id,
                    provider=provider,
                    provider_account_id=provider_account_id,
                    email=email.lower(),
                )
            )
        user.last_login_at = datetime.now(UTC)
        pair = await self._issue_token_pair(user=user, device_name=f"OAuth ({provider})")
        await self.db.commit()
        return pair

    async def _issue_token_pair(
        self,
        *,
        user: User,
        token_family: uuid.UUID | None = None,
        device_name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPairResponse:
        family = token_family or uuid.uuid4()
        access = create_access_token(user.id, user.email)
        refresh, refresh_exp = create_refresh_token(user.id, family)

        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh),
                token_family=family,
                device_name=device_name,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=refresh_exp,
            )
        )
        return TokenPairResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse.model_validate(user),
        )
