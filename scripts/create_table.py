"""Create missing project tables without modifying existing tables or data."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import Base, engine
from backend import models  # Register ORM tables in Base.metadata.


def create_tables():
    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)


def main():
    try:
        create_tables()
        print("資料表已確認建立：users、vehicle_ownerships、data_requests、raw_trajectories。")
        print("既有資料表與資料不會被修改；欄位變更需另外執行 migration。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
