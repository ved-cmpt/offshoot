"""Login and refresh-token rotation with reuse detection."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import unauthorized
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.services import audit


@dataclass
class IssuedTokens:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str


def _login_fingerprint(identifier: str) -> str:
    return hashlib.sha256(identifier.encode()).hexdigest()[:16]


def _issue(db: Session, user: User, family_id: uuid.UUID, settings: Settings) -> IssuedTokens:
    refresh = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    access, expires_in = create_access_token(str(user.id), settings)
    return IssuedTokens(user, access, expires_in, refresh)


def login(db: Session, identifier: str, password: str, settings: Settings) -> IssuedTokens:
    """Sign in with a username or an email, compared in lower case (ADR-050)."""
    normalized = identifier.strip().lower()
    user = db.scalar(select(User).where(or_(User.username == normalized, User.email == normalized)))
    if user is None:
        burn_password_check(password)
        authenticated = False
    else:
        authenticated = verify_password(user.password_hash, password) and user.active

    if user is None or not authenticated:
        audit.record(
            db,
            "auth.login_failed",
            actor_id=user.id if user else None,
            entity_type="user",
            entity_id=user.id if user else None,
            metadata={"login_fingerprint": _login_fingerprint(normalized)},
        )
        db.commit()
        raise unauthorized("Username or password is incorrect.", code="INVALID_CREDENTIALS")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    issued = _issue(db, user, uuid.uuid4(), settings)
    audit.record(db, "auth.login", actor_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()
    return issued


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def refresh(db: Session, presented: str | None, settings: Settings) -> IssuedTokens:
    invalid = unauthorized("Your session has ended. Please sign in again.", code="INVALID_REFRESH_TOKEN")
    if not presented:
        raise invalid
    # The row lock makes two concurrent uses of one token strictly ordered: the
    # second sees it revoked and is treated as reuse.
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(presented)).with_for_update()
    )
    if token is None:
        raise invalid

    if token.revoked_at is not None:
        _revoke_family(db, token.family_id)
        audit.record(
            db,
            "auth.refresh_reuse_detected",
            actor_id=token.user_id,
            entity_type="refresh_token_family",
            entity_id=token.family_id,
        )
        db.commit()
        raise invalid

    now = datetime.now(UTC)
    user = db.get(User, token.user_id)
    if token.expires_at <= now or user is None or not user.active:
        token.revoked_at = now
        db.commit()
        raise invalid

    token.revoked_at = now
    issued = _issue(db, user, token.family_id, settings)
    audit.record(db, "auth.refresh", actor_id=user.id, entity_type="refresh_token_family", entity_id=token.family_id)
    db.commit()
    return issued


def logout(db: Session, presented: str | None) -> None:
    if not presented:
        return
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(presented)))
    if token is None:
        return
    _revoke_family(db, token.family_id)
    audit.record(
        db, "auth.logout", actor_id=token.user_id, entity_type="refresh_token_family", entity_id=token.family_id
    )
    db.commit()
