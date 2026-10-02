"""MySQL connection and SQLAlchemy session management."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# Read backend/.env for local development. Existing process environment values
# take precedence, which also supports service and production deployments.
load_dotenv(Path(__file__).with_name(".env"), override=False)


def required_setting(name: str) -> str:
    """Return a required setting or stop startup with a clear error."""
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    if value.startswith("REPLACE_"):
        raise RuntimeError(f"Environment variable still contains a placeholder: {name}")
    return value


def database_port() -> int:
    raw_port = os.getenv("DB_PORT", "3306")
    try:
        port = int(raw_port)
    except ValueError:
        raise RuntimeError("DB_PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise RuntimeError("DB_PORT must be between 1 and 65535")
    return port


# URL.create safely handles special characters in the database password.
DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=required_setting("DB_USER"),
    password=required_setting("DB_PASSWORD"),
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=database_port(),
    database=required_setting("DB_NAME"),
    query={"charset": "utf8mb4"},
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class inherited by all SQLAlchemy ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Provide one database session per FastAPI request."""
    with SessionLocal() as session:
        yield session


def check_database_connection() -> None:
    """Open a connection and execute a harmless query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


if __name__ == "__main__":
    check_database_connection()
    print("MySQL connection succeeded.")
