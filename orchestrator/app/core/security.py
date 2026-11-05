"""Password hashing and token primitives."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

# argon2-cffi's PasswordHasher produces Argon2id hashes with its current recommended parameters.
_hasher = PasswordHasher()
# Verified when the email is unknown, so that login takes the same time either way.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: str, settings: Settings) -> tuple[str, int]:
    now = datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds
    # No role claim, on purpose: the role is loaded from the database on every request.
    payload = {
        "sub": user_id,
        "typ": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": secrets.token_urlsafe(8),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_access_token(token: str, settings: Settings) -> dict[str, Any] | None:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == "access" else None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    # The token is 256 random bits, so a fast hash is the right tool for lookup.
    return hashlib.sha256(token.encode()).hexdigest()
