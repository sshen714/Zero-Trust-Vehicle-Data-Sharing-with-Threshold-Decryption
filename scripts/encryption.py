import os
import re
import json
import base64
import hashlib
import hmac

from functools import lru_cache
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv, set_key
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ==================================================
# 路徑設定
# ==================================================

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / "backend" / ".env"

# 程式啟動時先讀一次 .env
load_dotenv(ENV_PATH)


# ==================================================
# 1. Key 產生
# ==================================================

def generate_key():
    """
    產生一把 AES-256 Key，
    並轉成 Base64 字串方便存進 .env。
    """

    key = AESGCM.generate_key(bit_length=256)

    return base64.b64encode(key).decode("utf-8")


# ==================================================
# 2. 初始化三把 Key
# ==================================================

def init_keys():
    """
    第一次初始化專案時使用。

    會產生：
    PLATE_KEY
    SPEED_KEY
    LOCATION_KEY

    如果 Key 已存在，不會覆蓋。
    """

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.touch(exist_ok=True)

    load_dotenv(ENV_PATH, override=True)

    key_names = [
        "PLATE_KEY",
        "SPEED_KEY",
        "LOCATION_KEY"
    ]

    for name in key_names:

        existing_key = os.getenv(name)

        if existing_key:
            print(f"{name} 已存在，跳過")
            continue

        new_key = generate_key()

        # 寫進 backend/.env
        set_key(
            str(ENV_PATH),
            name,
            new_key
        )

        # 同時更新目前 Python 程式的環境變數
        os.environ[name] = new_key

        print(f"{name} 已產生並寫入 backend/.env")

    # 清除可能存在的 Key cache
    load_key.cache_clear()
    get_lookup_key.cache_clear()

    print("\nKey 初始化完成")


# ==================================================
# 3. 載入 Key
# ==================================================

@lru_cache(maxsize=None)
def load_key(name):
    """
    從 .env 讀取指定 Key。

    第一次讀取後會暫存在記憶體，
    不會每加密一筆資料就重新讀 .env。
    """

    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"找不到 {name}\n"
            f"請先執行：\n"
            f"python3 encryption/encryption.py --init-keys"
        )

    try:
        key = base64.b64decode(
            value,
            validate=True
        )

    except Exception as exc:
        raise RuntimeError(
            f"{name} 不是有效的 Base64"
        ) from exc

    # AES-256 = 32 bytes
    if len(key) != 32:
        raise RuntimeError(
            f"{name} 必須是 AES-256 Key，"
            f"解碼後應為 32 bytes"
        )

    return key


# ==================================================
# 4. 產生車牌查詢專用 Key
# ==================================================

def derive_plate_lookup_key(plate_key):
    """
    從 PLATE_KEY 衍生出一把專門做
    plate_lookup 的 HMAC Key。

    不需要另外在 .env 儲存第四把 Key。
    """

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"vehicle-privacy-v1",
        info=b"plate-lookup"
    ).derive(plate_key)


@lru_cache(maxsize=1)
def get_lookup_key():
    """
    取得車牌查詢專用 Key。
    """

    plate_key = load_key("PLATE_KEY")

    return derive_plate_lookup_key(
        plate_key
    )


# ==================================================
# 5. AES-GCM 共用加密函式
# ==================================================

def encrypt_value(value, key, aad):
    """
    使用 AES-256-GCM 加密單一資料。

    最後儲存：
        Base64(nonce + ciphertext + tag)

    AESGCM.encrypt() 產生的 ciphertext
    已包含 authentication tag。
    """

    aes = AESGCM(key)

    # 每次加密都產生新的 12-byte nonce
    nonce = os.urandom(12)

    plaintext = str(value).encode("utf-8")

    ciphertext = aes.encrypt(
        nonce,
        plaintext,
        aad
    )

    # 解密時需要 nonce，所以一起保存
    encrypted_data = nonce + ciphertext

    # 轉 Base64，方便存在 MySQL TEXT 欄位
    return base64.b64encode(
        encrypted_data
    ).decode("utf-8")


# ==================================================
# 6. 車牌格式統一
# ==================================================

def normalize_plate(plate):
    """
    將不同格式的車牌統一。

    ABC-1234
    abc-1234
    ABC 1234

    都變成：

    ABC1234
    """

    plate = str(plate).strip().upper()

    return re.sub(
        r"[\s-]+",
        "",
        plate
    )


# ==================================================
# 7. 產生車牌查詢碼
# ==================================================

def make_plate_lookup(plate):
    """
    產生固定的 HMAC 查詢碼。

    同一車牌：
        ABC-1234 -> abc123...
        ABC-1234 -> abc123...

    用來讓 SQL 可以找出同一台車的資料。

    注意：
    plate_lookup 不是拿來解密車牌的。
    """

    normalized_plate = normalize_plate(
        plate
    )

    lookup_key = get_lookup_key()

    return hmac.new(
        lookup_key,
        normalized_plate.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


# ==================================================
# 8. 車牌加密
# ==================================================

def encrypt_plate(plate):
    """
    使用 PLATE_KEY 加密車牌。
    """

    plate_key = load_key("PLATE_KEY")

    normalized_plate = normalize_plate(
        plate
    )

    return encrypt_value(
        normalized_plate,
        plate_key,
        b"plate"
    )


# ==================================================
# 9. 車速加密
# ==================================================

def encrypt_speed(speed_kmh):
    """
    使用 SPEED_KEY 加密車速。
    """

    speed_key = load_key("SPEED_KEY")

    return encrypt_value(
        float(speed_kmh),
        speed_key,
        b"speed_kmh"
    )


# ==================================================
# 10. GPS 位置加密
# ==================================================

def encrypt_location(lat, lng):
    """
    把 lat / lng 合成一組資料，
    再使用 LOCATION_KEY 一起加密。
    """

    location_key = load_key(
        "LOCATION_KEY"
    )

    location = {
        "lat": float(lat),
        "lng": float(lng)
    }

    location_json = json.dumps(
        location,
        separators=(",", ":")
    )

    return encrypt_value(
        location_json,
        location_key,
        b"location"
    )


# ==================================================
# 11. 加密單筆車輛資料
# ==================================================

def encrypt_record(
    plate,
    timestamp,
    lat,
    lng,
    speed_kmh
):
    """
    把一整筆車輛資料加密。

    原本：

        plate
        timestamp
        lat
        lng
        speed_kmh

    變成：

        plate_enc
        plate_lookup
        timestamp
        location_enc
        speed_enc
    """

    return {
        "plate_enc": encrypt_plate(
            plate
        ),

        "plate_lookup": make_plate_lookup(
            plate
        ),

        # timestamp 保持明文
        "timestamp": timestamp,

        "location_enc": encrypt_location(
            lat,
            lng
        ),

        "speed_enc": encrypt_speed(
            speed_kmh
        )
    }


# ==================================================
# 12. 加密整個 DataFrame
# ==================================================

def encrypt_dataframe(
    df,
    plate_column="vehicle_id"
):
    """
    一次加密很多筆車輛資料。

    預期輸入欄位：

        vehicle_id
        timestamp
        lat
        lng
        speed_kmh
    """

    required_columns = {
        plate_column,
        "timestamp",
        "lat",
        "lng",
        "speed_kmh"
    }

    missing_columns = (
        required_columns - set(df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"缺少欄位：{missing_columns}"
        )

    encrypted_rows = []

    data = df[
        [
            plate_column,
            "timestamp",
            "lat",
            "lng",
            "speed_kmh"
        ]
    ]

    for (
        plate,
        timestamp,
        lat,
        lng,
        speed_kmh
    ) in data.itertuples(
        index=False,
        name=None
    ):

        encrypted_rows.append(
            encrypt_record(
                plate=plate,
                timestamp=timestamp,
                lat=lat,
                lng=lng,
                speed_kmh=speed_kmh
            )
        )

    return pd.DataFrame(
        encrypted_rows
    )

# ==================================================
# 主程式
# ==================================================

if __name__ == "__main__":

    import sys

    if "--init-keys" in sys.argv:

        init_keys()

    else:

        df = pd.DataFrame([
            {
                "vehicle_id": "ABC-1234",
                "timestamp": "2026-09-07 17:30:00",
                "lat": 25.033123,
                "lng": 121.543456,
                "speed_kmh": 42.5
            },
            {
                "vehicle_id": "ABC-1234",
                "timestamp": "2026-09-07 17:30:05",
                "lat": 25.033200,
                "lng": 121.543500,
                "speed_kmh": 43.1
            },
            {
                "vehicle_id": "XYZ-5678",
                "timestamp": "2026-09-07 17:31:00",
                "lat": 25.034100,
                "lng": 121.544200,
                "speed_kmh": 31.8
            }
        ])

        print("原始資料：")
        print(df.to_string(index=False))

        encrypted_df = encrypt_dataframe(df)

        print("\n加密後資料：")
        print(
            encrypted_df.to_string(
                index=False
            )
        )