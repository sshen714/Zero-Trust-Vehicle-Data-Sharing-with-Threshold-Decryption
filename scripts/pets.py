import hashlib
import hmac
import secrets

import numpy as np
import pandas as pd


# ==================================================
# 基本設定
# ==================================================

LAT0 = 25.0330
LNG0 = 121.5430

MX = 111320.0 * np.cos(np.radians(LAT0))
MY = 110540.0


# ==================================================
# 經緯度 <-> 公尺座標
# ==================================================

def to_xy(lat, lng):
    """
    經緯度轉成平面公尺座標。
    """

    x = (np.asarray(lng) - LNG0) * MX
    y = (np.asarray(lat) - LAT0) * MY

    return x, y


def to_ll(x, y):
    """
    平面公尺座標轉回經緯度。
    """

    lat = np.asarray(y) / MY + LAT0
    lng = np.asarray(x) / MX + LNG0

    return lat, lng


# ==================================================
# 1. 位置模糊
# ==================================================

def planar_laplace_noise(n, eps=0.02, rng=None):
    """
    產生平面 Laplace 位置雜訊。

    eps 越小：
        隱私越強
        位置偏移越大

    平均位移約為：
        2 / eps 公尺

    eps = 0.02
        -> 平均約 100 公尺
    """

    if rng is None:
        rng = np.random.default_rng()

    theta = rng.uniform(
        0,
        2 * np.pi,
        n
    )

    radius = rng.gamma(
        shape=2.0,
        scale=1.0 / eps,
        size=n
    )

    dx = radius * np.cos(theta)
    dy = radius * np.sin(theta)

    return dx, dy


def blur_location(
    df,
    eps=0.02,
    lat_column="lat",
    lng_column="lng",
    rng=None
):
    """
    對 DataFrame 裡的位置加入隨機偏移。
    """

    if rng is None:
        rng = np.random.default_rng()

    result = df.copy()

    x, y = to_xy(
        result[lat_column].values,
        result[lng_column].values
    )

    dx, dy = planar_laplace_noise(
        len(result),
        eps=eps,
        rng=rng
    )

    x = x + dx
    y = y + dy

    lat, lng = to_ll(
        x,
        y
    )

    result[lat_column] = np.round(
        lat,
        6
    )

    result[lng_column] = np.round(
        lng,
        6
    )

    return result


# ==================================================
# 2. 速度模糊
# ==================================================

def blur_speed(
    df,
    step=5,
    speed_column="speed_kmh"
):
    """
    將速度取整。

    42.7 -> 45
    31.2 -> 30
    """

    result = df.copy()

    result[speed_column] = (
        result[speed_column] / step
    ).round() * step

    return result


# ==================================================
# 3. 時間粗化
# ==================================================

def coarsen_time(
    df,
    interval_seconds=15,
    time_column="timestamp"
):
    """
    將時間粗化到固定區間。

    例如 interval_seconds = 15：

    17:30:07
        ->
    17:30:00

    17:30:22
        ->
    17:30:15
    """

    result = df.copy()

    result[time_column] = pd.to_datetime(
        result[time_column]
    )

    result[time_column] = (
        result[time_column]
        .dt.floor(
            f"{interval_seconds}s"
        )
    )

    return result


# ==================================================
# 4. 降低資料頻率
# ==================================================

def reduce_frequency(
    df,
    interval_seconds=15,
    vehicle_column="vehicle_id",
    time_column="timestamp"
):
    """
    原本例如每 5 秒一筆，
    降低成每 15 秒一筆。
    """

    result = df.copy()

    result[time_column] = pd.to_datetime(
        result[time_column]
    )

    result["_time_bucket"] = (
        result[time_column]
        .dt.floor(
            f"{interval_seconds}s"
        )
    )

    result = (
        result
        .sort_values(
            [
                vehicle_column,
                time_column
            ]
        )
        .drop_duplicates(
            [
                vehicle_column,
                "_time_bucket"
            ]
        )
    )

    result[time_column] = result[
        "_time_bucket"
    ]

    result = result.drop(
        columns=["_time_bucket"]
    )

    return result.reset_index(
        drop=True
    )


# ==================================================
# 5. 切分行程
# ==================================================

def split_trips(
    df,
    stop_gap=300,
    vehicle_column="vehicle_id",
    time_column="timestamp"
):
    """
    同一台車如果兩筆資料差超過 stop_gap 秒，
    視為新的一趟行程。

    預設：
        300 秒 = 5 分鐘
    """

    result = df.copy()

    result[time_column] = pd.to_datetime(
        result[time_column]
    )

    result = result.sort_values(
        [
            vehicle_column,
            time_column
        ]
    ).reset_index(drop=True)

    same_vehicle = (
        result[vehicle_column]
        ==
        result[vehicle_column].shift()
    )

    time_gap = (
        result[time_column]
        -
        result[time_column].shift()
    ).dt.total_seconds()

    new_trip = (
        ~same_vehicle
        |
        (time_gap > stop_gap)
    )

    result["trip_id"] = (
        new_trip.cumsum() - 1
    )

    return result


# ==================================================
# 6. 頭尾剪掉
# ==================================================

def trim_trip(
    df,
    min_distance=200,
    max_distance=500,
    lat_column="lat",
    lng_column="lng",
    trip_column="trip_id",
    rng=None
):
    """
    每一趟行程：
        起點隨機剪掉 200~500 m
        終點隨機剪掉 200~500 m
    """

    if rng is None:
        rng = np.random.default_rng()

    kept_groups = []

    for _, trip in df.groupby(
        trip_column,
        sort=False
    ):

        trip = trip.copy()

        if len(trip) < 2:
            continue

        x, y = to_xy(
            trip[lat_column].values,
            trip[lng_column].values
        )

        step_distance = np.hypot(
            np.diff(
                x,
                prepend=x[0]
            ),
            np.diff(
                y,
                prepend=y[0]
            )
        )

        cumulative = np.cumsum(
            step_distance
        )

        start_trim = rng.uniform(
            min_distance,
            max_distance
        )

        end_trim = rng.uniform(
            min_distance,
            max_distance
        )

        total_distance = cumulative[-1]

        keep = (
            (cumulative >= start_trim)
            &
            (
                cumulative
                <= total_distance - end_trim
            )
        )

        trimmed = trip.loc[
            keep
        ].copy()

        # 剩太少資料就整趟不公開
        if len(trimmed) < 5:
            continue

        kept_groups.append(
            trimmed
        )

    if not kept_groups:
        return df.iloc[0:0].copy()

    return pd.concat(
        kept_groups,
        ignore_index=True
    )


# ==================================================
# 7. 產生假名
# ==================================================

def make_pseudonym(
    key,
    vehicle_id,
    trip_id,
    segment
):
    """
    使用 HMAC-SHA256 產生假名。

    真實：
        ABC1234

    公開：
        P83A72F...
    """

    message = (
        f"{vehicle_id}|"
        f"{trip_id}|"
        f"{segment}"
    ).encode("utf-8")

    digest = hmac.new(
        key,
        message,
        hashlib.sha256
    ).hexdigest()

    return "P" + digest[:12]


# ==================================================
# 8. 中途換假名 + 靜默期
# ==================================================

def change_pseudonym(
    df,
    min_gap=30,
    max_gap=60,
    silent_min=15,
    silent_max=40,
    vehicle_column="vehicle_id",
    trip_column="trip_id",
    time_column="timestamp",
    rng=None
):
    """
    每隔 30~60 秒換一次假名。

    換假名前後加入 15~40 秒靜默期。

    這是簡化版：
    目前先不判斷是否真的位於混合區，
    後續可以再加入 crowd >= k 條件。
    """

    if rng is None:
        rng = np.random.default_rng()

    key = secrets.token_bytes(32)

    result_rows = []

    for trip_id, trip in df.groupby(
        trip_column,
        sort=False
    ):

        trip = trip.sort_values(
            time_column
        ).copy()

        if trip.empty:
            continue

        vehicle_id = str(
            trip.iloc[0][vehicle_column]
        )

        segment = 0

        first_time = pd.to_datetime(
            trip.iloc[0][time_column]
        )

        segment_start = first_time

        gap = rng.uniform(
            min_gap,
            max_gap
        )

        silent_until = None

        for _, row in trip.iterrows():

            current_time = pd.to_datetime(
                row[time_column]
            )

            if (
                silent_until is not None
                and current_time < silent_until
            ):
                continue

            elapsed = (
                current_time
                -
                segment_start
            ).total_seconds()

            if elapsed >= gap:

                segment += 1

                silence = rng.uniform(
                    silent_min,
                    silent_max
                )

                silent_until = (
                    current_time
                    +
                    pd.to_timedelta(
                        silence,
                        unit="s"
                    )
                )

                segment_start = silent_until

                gap = rng.uniform(
                    min_gap,
                    max_gap
                )

                continue

            new_row = row.copy()

            new_row["pseudo_id"] = (
                make_pseudonym(
                    key,
                    vehicle_id,
                    trip_id,
                    segment
                )
            )

            result_rows.append(
                new_row
            )

    if not result_rows:
        return df.iloc[0:0].copy()

    result = pd.DataFrame(
        result_rows
    )

    # 公開資料不要留下真實 vehicle_id
    result = result.drop(
        columns=[vehicle_column],
        errors="ignore"
    )

    return result.reset_index(
        drop=True
    )


# ==================================================
# 9. Owner 用 PETs
# ==================================================

def apply_owner_pets(
    df,
    location_eps=0.02,
    speed_step=5,
    rng=None
):
    """
    Owner：
        時間精準
        位置模糊
        速度模糊
    """

    result = df.copy()

    result = blur_location(
        result,
        eps=location_eps,
        rng=rng
    )

    result = blur_speed(
        result,
        step=speed_step
    )

    return result


# ==================================================
# 10. Researcher 完整 PETs
# ==================================================

def apply_researcher_pets(
    df,
    location_eps=0.02,
    speed_step=5,
    interval_seconds=15,
    rng=None
):
    """
    Researcher：

    1. 切 trip
    2. 頭尾剪掉
    3. 中途換假名
    4. 靜默期
    5. 位置偏移
    6. 降低頻率
    7. 時間粗化
    8. 速度取整
    """

    if rng is None:
        rng = np.random.default_rng()

    result = df.copy()
    result = split_trips(
        result
    )
    # 2. 去頭尾
    result = trim_trip(
        result,
        rng=rng
    )
    # 3 + 4. 假名 + 靜默期
    result = change_pseudonym(
        result,
        rng=rng
    )
    # 5. 位置偏移
    result = blur_location(
        result,
        eps=location_eps,
        rng=rng
    )
    # 6. 降低頻率
    result = reduce_frequency(
        result,
        interval_seconds=interval_seconds,
        vehicle_column="pseudo_id"
    )
    # 7. 時間粗化
    result = coarsen_time(
        result,
        interval_seconds=interval_seconds
    )
    # 8. 速度取整
    result = blur_speed(
        result,
        step=speed_step
    )
    # trip_id 是內部欄位，不公開
    result = result.drop(
        columns=["trip_id"],
        errors="ignore"
    )

    return result


# ==================================================
# 11. Visitor 車流統計
# ==================================================

def aggregate_traffic(
    df,
    interval="15min",
    speed_column="speed_kmh",
    time_column="timestamp"
):
    result = dfcopy()

    result[time_column] = pd.to_datetime(
        result[time_column]
    )

    result["time_bucket"] = (
        result[time_column]
        .dt.floor(interval)
    )

    traffic = (
        result
        .groupby("time_bucket")
        .agg(
            vehicle_count=(
                speed_column,
                "size"
            ),
            average_speed=(
                speed_column,
                "mean"
            )
        )
        .reset_index()
    )

    traffic[
        "average_speed"
    ] = traffic[
        "average_speed"
    ].round(1)

    # 簡單 Demo 用壅塞判定
    traffic[
        "congestion"
    ] = np.where(
        traffic["average_speed"] < 20,
        "high",
        np.where(
            traffic["average_speed"] < 35,
            "medium",
            "low"
        )
    )
    return traffic

if __name__ == "__main__":
    data = pd.DataFrame([
        {
            "vehicle_id": "ABC1234",
            "timestamp": "2026-09-07 17:30:00",
            "lat": 25.033123,
            "lng": 121.543456,
            "speed_kmh": 42.7
        },
        {
            "vehicle_id": "ABC1234",
            "timestamp": "2026-09-07 17:30:05",
            "lat": 25.033200,
            "lng": 121.543500,
            "speed_kmh": 41.2
        },
        {
            "vehicle_id": "ABC1234",
            "timestamp": "2026-09-07 17:30:10",
            "lat": 25.033300,
            "lng": 121.543600,
            "speed_kmh": 39.8
        }
    ])
    print("===== 原始資料 =====")
    print(
        data.to_string(
            index=False
        )
    )
    owner = apply_owner_pets(
        data
    )
    print("\n===== Owner PETs =====")
    print(
        owner.to_string(
            index=False
        )
    )