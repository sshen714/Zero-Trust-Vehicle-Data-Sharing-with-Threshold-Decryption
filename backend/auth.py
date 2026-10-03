"""Password hashing and JWT creation/validation helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from .database import required_setting


JWT_ALGORITHM = "HS256"
JWT_ISSUER = "zero-trust-vehicle-data-sharing"
JWT_AUDIENCE = "zero-trust-vehicle-data-sharing-api"

JWT_SECRET = required_setting("JWT_SECRET")
if len(JWT_SECRET.encode("utf-8")) < 32:
    raise RuntimeError("JWT_SECRET must contain at least 32 UTF-8 bytes")


def token_lifetime_minutes() -> int:
    """Read and validate the access-token lifetime."""
    raw_minutes = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    try:
        minutes = int(raw_minutes)
    except ValueError:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be an integer") from None
    if not 1 <= minutes <= 60:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 60")
    return minutes


TOKEN_LIFETIME_MINUTES = token_lifetime_minutes()
TOKEN_LIFETIME_SECONDS = TOKEN_LIFETIME_MINUTES * 60


def password_bytes(password: str) -> bytes:
    """Encode a password and enforce bcrypt's input limit."""
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return encoded


def hash_password(password: str) -> str:
    """Create a salted bcrypt password hash using cost factor 12."""
    return bcrypt.hashpw(password_bytes(password), bcrypt.gensalt(rounds=12)).decode(
        "ascii"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Compare a password with a stored bcrypt hash without raising on bad input."""
    try:
        return bcrypt.checkpw(password_bytes(password), password_hash.encode("ascii"))
    except (UnicodeError, ValueError):
        return False


# Login will use this when a username does not exist, so missing and existing
# accounts perform a bcrypt check and are harder to distinguish by response time.
DUMMY_PASSWORD_HASH = hash_password("dummy-password-used-only-for-timing")


def create_access_token(user_id: int) -> str:
    """Create a signed, short-lived access token for a database user ID."""
    if user_id <= 0:
        raise ValueError("user_id must be positive")
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_LIFETIME_MINUTES),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate a token and return claims, or raise jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["sub", "iat", "exp", "iss", "aud"]},
    )
