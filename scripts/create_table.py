"""Create missing project tables without modifying existing tables or data."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import models  # noqa: F401 - register every ORM table in Base.metadata
from backend.database import Base, engine


def create_tables() -> list[str]:
    """Create missing tables and return the complete ORM table list."""
    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)
    return sorted(Base.metadata.tables)


def main():
    try:
        table_names = create_tables()
        print(f"資料表已確認建立：{'、'.join(table_names)}。")
        print("既有資料表與資料不會被修改；欄位變更需另外執行 migration。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
