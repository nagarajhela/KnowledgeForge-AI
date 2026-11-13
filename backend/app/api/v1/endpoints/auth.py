from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limiter
from app.core.tenant import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    EmailVerifyRequest,
    LoginRequest,
    LogoutRequest,
    OAuthAuthorizeResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    SessionInfoResponse,
    TokenPairResponse,
)
from app.schemas.common import MessageResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=TokenPairResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and optional starter organization",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    ip = request.client.host if request.client else None
    await rate_limiter.check_rate_limit(f"auth:register:{ip or 'unknown'}", limit=30)
    return await AuthService(db).register(
        payload,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/login", response_model=TokenPairResponse, summary="Authenticate with email and password")
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    ip = request.client.host if request.client else None
    await rate_limiter.check_rate_limit(f"auth:login:{ip or 'unknown'}", limit=60)
    return await AuthService(db).login(
        payload,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/refresh", response_model=TokenPairResponse, summary="Rotate refresh token")
async def refresh_token(
    payload: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    ip = request.client.host if request.client else None
    return await AuthService(db).refresh(
        payload.refresh_token,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/logout", response_model=MessageResponse, summary="Revoke active refresh session(s)")
async def logout(
    payload: LogoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await AuthService(db).logout(
        user,
        raw_refresh_token=payload.refresh_token,
        revoke_all=payload.revoke_all_sessions,
    )
    return MessageResponse(message="Logged out successfully")


@router.get("/sessions", response_model=list[SessionInfoResponse], summary="List active and past sessions")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionInfoResponse]:
    sessions = await AuthService(db).list_sessions(user.id)
    return [SessionInfoResponse.model_validate(s) for s in sessions]


@router.post("/verify-email", response_model=MessageResponse, summary="Verify email address via token")
async def verify_email(
    payload: EmailVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await AuthService(db).verify_email(payload.token)
    return MessageResponse(message="Email verified")


@router.post("/password-reset/request", response_model=MessageResponse, summary="Request password reset")
async def request_password_reset(
    payload: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await AuthService(db).request_password_reset(payload.email)
    return MessageResponse(message="If an account exists, a password reset link has been issued.")


@router.post("/password-reset/confirm", response_model=MessageResponse, summary="Confirm password reset")
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await AuthService(db).confirm_password_reset(payload.token, payload.new_password)
    return MessageResponse(message="Password updated successfully")


@router.get(
    "/oauth/{provider}/authorize",
    response_model=OAuthAuthorizeResponse,
    summary="Get OAuth2 authorization URL for Google or Microsoft",
)
async def oauth_authorize(provider: str) -> OAuthAuthorizeResponse:
    return AuthService.build_oauth_authorization_url(provider)


@router.post(
    "/oauth/{provider}/callback",
    response_model=TokenPairResponse,
    summary="Exchange OAuth2 callback code and signed state for KnowledgeForge JWT pair",
)
async def oauth_callback(
    provider: str,
    code: str,
    state: str | None = None,
    email: str | None = None,
    full_name: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    return await AuthService(db).handle_oauth_callback(
        provider=provider,
        code=code,
        state=state,
        mock_email=email,
        mock_full_name=full_name,
    )
