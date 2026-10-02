"""Pydantic request and response schemas for authentication APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import Role


class RegisterRequest(BaseModel):
    """Public registration input; role and account state are not accepted."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=12, max_length=72)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, username: object) -> object:
        """Ignore accidental surrounding whitespace in the username only."""
        return username.strip() if isinstance(username, str) else username

    @field_validator("password")
    @classmethod
    def validate_bcrypt_length(cls, password: str) -> str:
        """Reject input bcrypt cannot process without truncation."""
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return password


class UserResponse(BaseModel):
    """Safe public representation of a user; no password hash is exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Response returned after a successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(gt=0, description="Token lifetime in seconds")
