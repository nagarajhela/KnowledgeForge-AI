from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserProfileUpdateRequest, UserResponse
from app.schemas.common import MessageResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse, summary="Get authenticated user profile")
async def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse, summary="Update authenticated user profile")
async def update_me(
    payload: UserProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    updated = await AuthService(db).update_profile(user, payload)
    return UserResponse.model_validate(updated)


@router.delete("/me", response_model=MessageResponse, summary="GDPR right-to-erasure account anonymization")
async def delete_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await AuthService(db).gdpr_anonymize_user(user)
    return MessageResponse(message="Account anonymized and all active sessions revoked.")
