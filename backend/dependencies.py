"""FastAPI dependencies for authentication and role authorization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .auth import decode_access_token
from .database import get_db
from .models import Role, User


DbSession = Annotated[Session, Depends(get_db)]

# This also adds the Bearer authentication scheme to the generated API docs.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def credentials_exception() -> HTTPException:
    """Build a fresh 401 response for missing, invalid, or expired credentials."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Validate the JWT, then reload the current user state from MySQL."""
    try:
        claims = decode_access_token(token)
        subject = claims["sub"]
    except (jwt.InvalidTokenError, KeyError):
        raise credentials_exception() from None

    # MySQL INTEGER is signed by default. Strict parsing prevents values such as
    # floats, signs, whitespace, or Unicode digits from becoming user IDs.
    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdigit()
    ):
        raise credentials_exception()
    user_id = int(subject)
    if not 1 <= user_id <= 2_147_483_647:
        raise credentials_exception()

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception()
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: Role) -> Callable[[CurrentUser], User]:
    """Create a dependency that permits only the listed database roles."""
    if not allowed_roles:
        raise ValueError("require_roles needs at least one allowed role")

    def check_role(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return check_role
