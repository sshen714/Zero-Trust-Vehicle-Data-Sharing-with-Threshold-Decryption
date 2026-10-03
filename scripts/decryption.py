import sys
import json
import base64
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


# ==================================================
# 找到專案根目錄
# ==================================================

BASE_DIR = Path(__file__).resolve().parents[1]

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# 直接使用 encryption.py 已經寫好的 load_key()
from scripts.encryption import load_key


# ==================================================
# AES-GCM 共用解密函式
# ==================================================

def decrypt_value(encrypted_value, key, aad):
    """
    解密 encryption.py 產生的資料。

    encryption.py 儲存格式：
        Base64(nonce + ciphertext + tag)

    回傳：
        解密後的字串
    """

    try:
        encrypted_data = base64.b64decode(
            encrypted_value,
            validate=True
        )

    except Exception as exc:
        raise RuntimeError(
            "密文不是有效的 Base64"
        ) from exc


    # AES-GCM nonce = 前 12 bytes
    nonce = encrypted_data[:12]

    # 剩下的是 ciphertext + authentication tag
    ciphertext = encrypted_data[12:]


    aes = AESGCM(key)

    try:
        plaintext = aes.decrypt(
            nonce,
            ciphertext,
            aad
        )

    except InvalidTag as exc:
        raise RuntimeError(
            "解密失敗：Key、AAD 不正確，或資料已被修改"
        ) from exc


    return plaintext.decode("utf-8")


# ==================================================
# 車牌解密
# ==================================================

def decrypt_plate(plate_enc):
    """
    plate_enc
        ↓
    PLATE_KEY
        ↓
    原始車牌
    """

    plate_key = load_key(
        "PLATE_KEY"
    )

    return decrypt_value(
        plate_enc,
        plate_key,
        b"plate"
    )


# ==================================================
# 車速解密
# ==================================================

def decrypt_speed(speed_enc):
    """
    speed_enc
        ↓
    SPEED_KEY
        ↓
    float 車速
    """

    speed_key = load_key(
        "SPEED_KEY"
    )

    plaintext = decrypt_value(
        speed_enc,
        speed_key,
        b"speed_kmh"
    )

    return float(
        plaintext
    )


# ==================================================
# GPS 位置解密
# ==================================================

def decrypt_location(location_enc):
    """
    location_enc
        ↓
    LOCATION_KEY
        ↓
    {
        "lat": ...,
        "lng": ...
    }
    """

    location_key = load_key(
        "LOCATION_KEY"
    )

    plaintext = decrypt_value(
        location_enc,
        location_key,
        b"location"
    )

    location = json.loads(
        plaintext
    )

    return {
        "lat": float(
            location["lat"]
        ),
        "lng": float(
            location["lng"]
        )
    }


# ==================================================
# 單筆資料解密
# ==================================================

def decrypt_record(
    plate_enc=None,
    timestamp=None,
    location_enc=None,
    speed_enc=None
):
    """
    依照實際有提供的欄位進行解密。

    不一定每個欄位都要解密。
    """

    result = {}

    if plate_enc is not None:
        result["plate"] = decrypt_plate(
            plate_enc
        )

    if timestamp is not None:
        result["timestamp"] = timestamp

    if location_enc is not None:
        result["location"] = decrypt_location(
            location_enc
        )

    if speed_enc is not None:
        result["speed_kmh"] = decrypt_speed(
            speed_enc
        )

    return result

if __name__ == "__main__":
    from scripts.encryption import (
        encrypt_plate,
        encrypt_speed,
        encrypt_location
    )

    plate = "ABC-1234"
    speed = 42.5
    lat = 25.033123
    lng = 121.543456


    print("===== 原始資料 =====")
    print("車牌：", plate)
    print("速度：", speed)
    print("位置：", lat, lng)


    # 加密
    plate_enc = encrypt_plate(
        plate
    )

    speed_enc = encrypt_speed(
        speed
    )

    location_enc = encrypt_location(
        lat,
        lng
    )


    print("\n===== 加密後 =====")
    print("車牌：", plate_enc)
    print("速度：", speed_enc)
    print("位置：", location_enc)


    # 解密
    plate_dec = decrypt_plate(
        plate_enc
    )

    speed_dec = decrypt_speed(
        speed_enc
    )

    location_dec = decrypt_location(
        location_enc
    )


    print("\n===== 解密後 =====")
    print("車牌：", plate_dec)
    print("速度：", speed_dec)
    print("位置：", location_dec)