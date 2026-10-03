"""FastAPI application for registration, login, and user authorization."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated, List

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from .auth import (
    DUMMY_PASSWORD_HASH,
    TOKEN_LIFETIME_SECONDS,
    create_access_token,
    hash_password,
    verify_password,
)
from .database import Base, engine
from .dependencies import CurrentUser, DbSession, require_roles
from .models import Role, User
from .schemas import RegisterRequest, TokenResponse, UserResponse


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


@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(data: RegisterRequest, db: DbSession) -> User:
    """Create a public account with the fixed visitor role."""
    email = str(data.email)
    existing_id = db.scalar(
        select(User.id).where(
            or_(User.username == data.username, User.email == email)
        )
    )
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists",
        )

    user = User(
        username=data.username,
        email=email,
        hashed_password=hash_password(data.password),
        role=Role.VISITOR,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        # Keep the unique database constraints as the final concurrency guard.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists",
        ) from None
    return user


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
