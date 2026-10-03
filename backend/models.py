"""SQLAlchemy ORM models for users and roles."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, String, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Role(StrEnum):
    """Roles recognized by the backend authorization system."""

    OWNER = "owner"
    VISITOR = "visitor"
    VENDOR = "vendor"
    SUPERVISOR_A = "supervisor_a"
    SUPERVISOR_B = "supervisor_b"
    ADMIN = "admin"
    RESEARCHER = "researcher"
    POLICE = "police"


class User(Base):
    """A login account stored in the MySQL users table."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(254), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda roles: [role.value for role in roles]),
        default=Role.VISITOR,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class DataRequest(Base):
    """Each supervisor's independent decision is retained separately."""

    __tablename__ = "data_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(500))
    decision_a: Mapped[str] = mapped_column(String(16), default="pending")
    decision_b: Mapped[str] = mapped_column(String(16), default="pending")
    reviewer_a: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewer_b: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
