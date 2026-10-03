import numpy as np
import pandas as pd
BASE_DATE = pd.Timestamp("2026-09-07")
LAT0, LNG0 = 25.0330, 121.5430
MX = 111320.0 * np.cos(np.radians(LAT0))   # 1 度經度約幾公尺
MY = 110540.0                              # 1 度緯度約幾公尺

def to_ll(x, y):
    return np.asarray(y) / MY + LAT0, np.asarray(x) / MX + LNG0
def generate_raw(n_veh, n_days, rng, block=250, n=17, dt=5):
    """棋盤式路網上的通勤模擬：固定住家/公司、早晚尖峰、市中心尖峰壅塞、
    15% 的車每週一次下班後去醫院。回傳 (原始資料, 醫院座標)。"""
    size = block * (n - 1)
    half = size / 2.0
    hospital_node = (n // 4, (3 * n) // 4)
    hospital_xy = np.array([hospital_node[0] * block - half, hospital_node[1] * block - half])
    rows = []

    def node_xy(nd):
        return np.array([nd[0] * block - half, nd[1] * block - half], float)

    def limit_kmh(x, y, hour):
        peak = (7 <= hour < 9.5) or (17 <= hour < 19.5)
        d = (x * x + y * y) ** 0.5
        if peak and d < 1000:
            return 18.0
        if peak and d < 1800:
            return 30.0
        return 45.0

    def route(a, b, p_from, p_to):
        """起點 → 最近路口 → 沿路網（先橫、再直、再橫）→ 終點"""
        dx = b[0] - a[0]
        k = int(rng.integers(0, abs(dx) + 1)) * (1 if dx >= 0 else -1)
        nodes = [a, (a[0] + k, a[1]), (a[0] + k, b[1]), b]
        pts = [p_from] + [node_xy(nd) for nd in nodes] + [p_to]
        out = [pts[0]]
        for p in pts[1:]:
            if np.hypot(*(p - out[-1])) > 1e-6:
                out.append(p)
        return np.array(out)

    def drive(vid, pts, t0, style):
        seg = np.diff(pts, axis=0)
        L = np.hypot(seg[:, 0], seg[:, 1]).tolist()
        P, S = pts.tolist(), seg.tolist()
        noise = rng.uniform(0.85, 1.15, 4000).tolist()
        s, t, k, start, i = 0.0, int(t0), 0, 0.0, 0
        while True:
            while k < len(L) and s >= start + L[k]:
                start += L[k]
                k += 1
            if k == len(L):
                break
            f = (s - start) / L[k]
            px, py = P[k][0] + S[k][0] * f, P[k][1] + S[k][1] * f
            v = limit_kmh(px, py, (t % 86400) / 3600.0) * style * noise[i % 4000]
            rows.append((vid, t, px, py, v))
            s += v / 3.6 * dt
            t += dt
            i += 1
        rows.append((vid, t, P[-1][0], P[-1][1], 0.0))
        return t

    for i in range(n_veh):
        vid = f"V{i:05d}"
        home_node = (int(rng.integers(0, n)), int(rng.integers(0, n)))
        while True:  # 公司偏向市中心，且離家至少 6 個街區
            work_node = tuple(int(c) for c in np.clip(np.round(rng.normal(n / 2, n / 7, 2)), 0, n - 1))
            if abs(work_node[0] - home_node[0]) + abs(work_node[1] - home_node[1]) >= 6:
                break
        home = node_xy(home_node) + rng.uniform(-100, 100, 2)
        work = node_xy(work_node) + rng.uniform(-60, 60, 2)
        style = rng.uniform(0.9, 1.1)
        am = 7.75 + rng.normal(0, 0.5)
        pm = 17.75 + rng.normal(0, 0.5)
        hosp_day = int(rng.integers(0, n_days)) if rng.random() < 0.15 else -1

        for d in range(n_days):
            t0 = d * 86400 + (am + rng.normal(0, 0.08)) * 3600
            drive(vid, route(home_node, work_node, home, work), t0, style)
            t1 = d * 86400 + (pm + rng.normal(0, 0.08)) * 3600
            if d == hosp_day:
                t_arr = drive(vid, route(work_node, hospital_node, work, hospital_xy), t1, style)
                drive(vid, route(hospital_node, home_node, hospital_xy, home), t_arr + 2400, style)
            else:
                drive(vid, route(work_node, home_node, work, home), t1, style)

    df = pd.DataFrame(rows, columns=["vehicle_id", "t", "x", "y", "speed_kmh"])
    return df, hospital_xy


def save_raw_database(df, table_name="encrypted_trajectories"):
    import sys
    from pathlib import Path
    from sqlalchemy import text
    root = Path(__file__).resolve().parents[1]

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from backend.database import engine
    from encryption import encrypt_dataframe
    lat, lng = to_ll(
        df.x.values,
        df.y.values
    )

    plain_data = pd.DataFrame({
        "vehicle_id": df.vehicle_id.values,
        "timestamp": BASE_DATE + pd.to_timedelta(
            df.t.values,
            unit="s"
        ),
        "lat": np.round(
            lat,
            6
        ),
        "lng": np.round(
            lng,
            6
        ),
        "speed_kmh": np.round(
            df.speed_kmh.values,
            1
        ),
    })

    encrypted_data = encrypt_dataframe(
        plain_data
    )

    with engine.begin() as conn:

        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    `id` BIGINT NOT NULL AUTO_INCREMENT,

                    `plate_enc` TEXT NOT NULL,

                    `plate_lookup` CHAR(64) NOT NULL,

                    `timestamp` DATETIME NOT NULL,

                    `location_enc` TEXT NOT NULL,

                    `speed_enc` TEXT NOT NULL,

                    PRIMARY KEY (`id`),

                    INDEX `idx_plate_lookup` (`plate_lookup`),
                    INDEX `idx_timestamp` (`timestamp`)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                """
            )
        )
        encrypted_data.to_sql(
            name=table_name,
            con=conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000,
        )
    print(
        f"成功寫入 {len(encrypted_data)} 筆加密資料到 MySQL：{table_name}"
    )

if __name__ == "__main__":
    rng = np.random.default_rng(42)

    # 模擬 10 台車、2 天
    raw, hospital_xy = generate_raw(
        n_veh=10,
        n_days=2,
        rng=rng,
    )

    save_raw_database(raw, table_name="encrypted_trajectories")

    print(raw.head())
    print(f"共產生 {len(raw)} 筆紀錄")
    print(f"醫院座標：{hospital_xy}")
    print("已儲存 encrypted_trajectories.csv")