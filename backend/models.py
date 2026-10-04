"""SQLAlchemy ORM models for accounts and vehicle-data workflows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
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


class Vehicle(Base):
    """A vehicle referenced by an opaque ID and a non-reversible plate lookup."""

    __tablename__ = "vehicles"

    vehicle_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    plate_lookup: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class EncryptedTrajectory(Base):
    """Encrypted trajectory records used by the protected data workflow."""

    __tablename__ = "encrypted_trajectories"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    plate_enc: Mapped[str] = mapped_column(Text, nullable=False)
    plate_lookup: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    location_enc: Mapped[str] = mapped_column(Text, nullable=False)
    speed_enc: Mapped[str] = mapped_column(Text, nullable=False)


class VehicleOwnership(Base):
    """Map an owner account to a vehicle without duplicating account data."""

    __tablename__ = "vehicle_ownerships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.vehicle_id"), unique=True, nullable=False
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
