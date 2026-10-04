"""SQLAlchemy ORM models for accounts and vehicle-data workflows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
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
    """A vehicle known to the system, independent of its current owner."""

    __tablename__ = "vehicles"

    vehicle_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    plate_lookup: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class RawTrajectory(Base):
    """Plain simulated input retained only for development and demonstrations."""

    __tablename__ = "raw_trajectories"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    vehicle_id: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lat: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    lng: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)


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
