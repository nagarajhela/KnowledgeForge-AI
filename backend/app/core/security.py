import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.exceptions import AuthenticationError

_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        return False
    try:
        return _ph.verify(hashed_password, password)
    except VerifyMismatchError:
        return False


def hash_token(raw_token: str) -> str:
    """One-way SHA-256 hex digest for refresh tokens, API keys, and reset/invite tokens."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext_key_shown_once, key_prefix, sha256_hash)."""
    secret_part = secrets.token_urlsafe(32)
    raw_key = f"kf_live_{secret_part}"
    prefix = raw_key[:16]
    return raw_key, prefix, hash_token(raw_key)


def generate_opaque_token(nbytes: int = 32) -> tuple[str, str]:
    raw = secrets.token_urlsafe(nbytes)
    return raw, hash_token(raw)


def _fernet_instance() -> Fernet:
    digest = hashlib.sha256(settings.ENCRYPTION_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet_instance().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet_instance().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def create_access_token(
    user_id: uuid.UUID,
    email: str,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    exp = now + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID,
    token_family: uuid.UUID,
    expires_delta: timedelta | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + (expires_delta or timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "family": str(token_family),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    encoded = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded, exp


def decode_jwt(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired", error_code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token", error_code="invalid_token") from exc

    if expected_type and payload.get("type") != expected_type:
        raise AuthenticationError("Unexpected token type", error_code="invalid_token_type")
    return payload
