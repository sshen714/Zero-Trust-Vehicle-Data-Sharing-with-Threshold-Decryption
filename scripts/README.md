# Scripts 說明

此資料夾負責車輛資料的產生、加密、解密，以及 PETs（Privacy-Enhancing Technologies）隱私保護處理。

## 整體流程

### 資料寫入流程

```text
simulation_data.py
        ↓
encryption.py
        ↓
MySQL
```

`simulation_data.py` 先產生車輛模擬資料，再呼叫 `encryption.py` 將敏感欄位加密後寫入 `encrypted_trajectories`，不建立或寫入明文軌跡表。`vehicles` 只登記由 HMAC 查詢碼衍生的不透明內部 ID 與 `plate_lookup`，不保存解密後的車牌。

### 使用者查詢流程

```text
MySQL
  ↓
decryption.py
  ↓
pets.py
  ↓
依角色權限回傳資料
```

資料平常以密文形式儲存在 MySQL。只有在使用者提出查詢且通過權限驗證後，後端才會解密必要欄位，再依角色套用不同程度的 PETs 處理。

---

## simulation_data.py

負責產生模擬車輛軌跡資料。

原始資料包含：

- `vehicle_id`
- `timestamp`
- `lat`
- `lng`
- `speed_kmh`

模擬產生的 raw data 只存在程式記憶體中，接著交由 `encryption.py` 處理；MySQL 只保存加密後的結果。每次可查詢的資料都來自 `simulation_data.py` 產生的模擬資料。

資料庫目前主要儲存：

```text
plate_enc
plate_lookup
timestamp
location_enc
speed_enc
```

其中：

- `plate_enc`：加密後的車牌／車輛識別碼
- `plate_lookup`：供車牌查詢使用的固定 HMAC 查詢碼
- `timestamp`：保留明文，方便依時間區間查詢
- `location_enc`：加密後的位置
- `speed_enc`：加密後的速度

---

## encryption.py

負責敏感欄位的加密與金鑰初始化。

目前使用：

```text
AES-256-GCM
```

主要金鑰：

```text
PLATE_KEY
LOCATION_KEY
SPEED_KEY
```

金鑰儲存在：

```text
backend/.env
```

第一次使用時執行：

```bash
python3 scripts/encryption.py --init-keys
```

### 主要函式

- `generate_key()`：產生 AES-256 Key。
- `init_keys()`：初始化 `PLATE_KEY`、`LOCATION_KEY`、`SPEED_KEY`，並寫入 `backend/.env`。若金鑰已存在則不覆蓋。
- `load_key()`：從 `.env` 載入指定 Key。
- `encrypt_value()`：AES-GCM 共用加密函式。
- `encrypt_plate()`：加密車牌／車輛識別碼。
- `encrypt_location()`：將 `lat` 與 `lng` 組合後使用 `LOCATION_KEY` 加密。
- `encrypt_speed()`：使用 `SPEED_KEY` 加密速度。
- `make_plate_lookup()`：產生固定的 HMAC 查詢碼，使系統在不保存明文車牌的情況下仍可找到同一台車的紀錄。
- `encrypt_record()`：加密單筆車輛資料。
- `encrypt_dataframe()`：一次處理整批 DataFrame 資料。

---

## decryption.py

負責在使用者查詢資料時進行選擇性解密。

資料不會在登入後直接全部解密，而是：

```text
使用者提出查詢
        ↓
後端驗證角色與權限
        ↓
SQL 篩選必要資料
        ↓
只解密此次需要的欄位
        ↓
套用 PETs
        ↓
回傳結果
```

### 主要函式

- `decrypt_plate()`
- `decrypt_location()`
- `decrypt_speed()`
- `decrypt_record()`

例如合作廠商若只需要精準速度，後端可以只解密 `speed_enc`，而不需要解密 `location_enc`。

---

## pets.py

負責解密後的資料模糊化與隱私保護處理。

### 位置模糊

`blur_location()`：對 GPS 座標加入隨機偏移，避免直接暴露精準位置。

### 速度模糊

`blur_speed()`：將速度取整，例如：

```text
42.7 km/h
→
45 km/h
```

### 時間粗化

`coarsen_time()`：將精準時間轉為固定時間區間，例如：

```text
17:30:07
→
17:30:00
```

### 降低資料頻率

`reduce_frequency()`：例如：

```text
每 5 秒一筆
→
每 15 秒一筆
```

### 行程切分

`split_trips()`：依車輛與時間間隔將軌跡切分為不同 `trip_id`。

### 起訖點遮蔽

`trim_trip()`：每趟行程前後隨機移除約 200～500 公尺，降低住家、公司、醫院等敏感地點被推測的風險。

### 假名化與靜默期

`change_pseudonym()`：在行程途中更換假名，並加入 15～40 秒靜默期，降低不同軌跡片段被重新連結的可能性。

### 角色資料處理

- `apply_owner_pets()`：車主使用，保留精準時間，位置與速度模糊化。
- `apply_researcher_pets()`：交通研究者使用，套用完整 PETs，包括假名化、去頭尾、靜默期、位置偏移、降低頻率、時間粗化與速度取整。
- `aggregate_traffic()`：訪客使用，不提供單車資料，只輸出車流量、平均速度與壅塞程度等聚合統計。

---

## 角色與資料處理概念

### Owner

```text
精準時間
模糊位置
模糊速度
```

只能查詢帳號已綁定的車輛。

### Visitor

不提供單車級資料，只提供：

```text
車流量
平均速度
壅塞程度
```

### Partner

```text
精準時間
預設模糊位置
精準速度
```

取得主管 A 的 Email OTP 後，可依授權範圍解鎖精準位置。

### Supervisor A

```text
精準時間
精準位置
預設模糊速度
```

若需要精準速度，需取得主管 B 的 OTP。

### Supervisor B

```text
精準時間
預設模糊位置
精準速度
```

若需要精準位置，需取得主管 A 的 OTP。

### Admin

預設僅能取得模糊位置與模糊速度。

```text
主管 A OTP → 精準位置
主管 B OTP → 精準速度
```

### Researcher

可以取得單車級研究資料，但：

```text
車牌假名化
時間粗化
位置模糊
速度模糊
完整 PETs
```

### Police

依案件授權範圍查詢特定車牌、時間與欄位。

預設位置與速度仍為模糊資料；系統 Email OTP 驗證成功後，才依案件授權範圍提供精準位置及／或精準速度。

---

## 安全注意事項

請勿將以下檔案提交至 GitHub：

```text
backend/.env
```

其中可能包含：

```text
資料庫帳號與密碼
PLATE_KEY
LOCATION_KEY
SPEED_KEY
```

請確認 `.gitignore` 已包含：

```gitignore
backend/.env
.env
```
