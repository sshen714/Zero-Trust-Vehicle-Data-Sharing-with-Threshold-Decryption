import numpy as np
import sys
from pathlib import Path

# 專案根目錄
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

    
from scripts.simulation_data import (
    generate_raw,
    save_encrypted_database
)

from scripts.decryption import (
    decrypt_location,
    decrypt_speed,
    decrypt_plate
)

from scripts.pets import (
    apply_owner_pets,
    apply_researcher_pets,
    aggregate_traffic
)


# ==================================================
# 1. 產生模擬資料並寫入資料庫
# ==================================================

def generate_vehicle_data():

    rng = np.random.default_rng(42)

    raw, hospital_xy = generate_raw(
        n_veh=10,
        n_days=2,
        rng=rng
    )

    save_encrypted_database(raw)

    print(f"產生 {len(raw)} 筆資料")
    print(f"醫院座標：{hospital_xy}")


# ==================================================
# 2. Owner 資料處理
# ==================================================

def process_owner_data(df):

    return apply_owner_pets(
        df
    )


# ==================================================
# 3. Visitor 資料處理
# ==================================================

def process_visitor_data(df):

    return aggregate_traffic(
        df
    )


# ==================================================
# 4. Researcher 資料處理
# ==================================================

def process_researcher_data(df):

    return apply_researcher_pets(
        df
    )


# ==================================================
# Main
# ==================================================

if __name__ == "__main__":

    generate_vehicle_data()
