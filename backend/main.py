"""FastAPI application for registration, login, and user authorization."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated, List

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from .auth import (
    DUMMY_PASSWORD_HASH,
    TOKEN_LIFETIME_SECONDS,
    create_access_token,
    verify_password,
)
from .database import engine
from .dependencies import CurrentUser, DbSession, require_roles
from .models import Role, User
from .schemas import AccountLookupResponse, TokenResponse, UserResponse
from .workspace import public_router, router as workspace_router


def get_cors_origins() -> List[str]:
    """Return the explicitly allowed frontend origins."""
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError("CORS_ORIGINS must contain at least one origin")
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must list explicit origins, not '*'")
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create missing tables on startup and close the engine at shutdown."""
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    """Close the engine at shutdown; scripts/create_table.py handles table creation."""
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title="Zero Trust Vehicle Data Sharing API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(workspace_router)
app.include_router(public_router)


@app.post("/auth/login", response_model=TokenResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    response: Response,
) -> TokenResponse:
    """Verify credentials and issue a short-lived bearer token."""
    user = db.scalar(select(User).where(User.username == form.username))
    stored_hash = user.hashed_password if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(form.password, stored_hash)

    # Give unknown, incorrect-password, and inactive accounts the same response.
    if user is None or not password_valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=TOKEN_LIFETIME_SECONDS,
    )


@app.get("/auth/me", response_model=UserResponse)
def read_current_user(current_user: CurrentUser, response: Response) -> User:
    """Return the current account after JWT and database checks."""
    response.headers["Cache-Control"] = "no-store"
    return current_user


@app.get("/users", response_model=List[UserResponse])
def list_users(
    db: DbSession,
    admin_user: Annotated[User, Depends(require_roles(Role.ADMIN))],
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> List[User]:
    """Return a paginated list of users to administrators only."""
    # The dependency performs authorization; the endpoint does not need the user.
    del admin_user
    response.headers["Cache-Control"] = "no-store"
    users = db.scalars(select(User).order_by(User.id).offset(offset).limit(limit))
    return list(users.all())


@app.get("/users/lookup", response_model=AccountLookupResponse)
def lookup_user(
    db: DbSession,
    admin_user: Annotated[User, Depends(require_roles(Role.ADMIN))],
    response: Response,
    username: Annotated[str, Query(min_length=1, max_length=50)],
) -> User:
    """Look up one account by username, for administrators only."""
    del admin_user
    response.headers["Cache-Control"] = "no-store"
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None:
        raise HTTPException(status_code=404, detail="Account is not available")
    return user
