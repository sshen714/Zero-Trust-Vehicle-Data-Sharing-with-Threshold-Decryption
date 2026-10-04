# Backend 說明

此目錄包含零信任車輛資料分享專案目前使用的 FastAPI 後端。後端負責帳號註冊與登入、JWT 驗證、角色授權、MySQL 存取、車主軌跡查詢，以及合作廠商的雙主管審核流程。

## 目錄結構

| 檔案 | 用途 |
| --- | --- |
| `main.py` | 建立 FastAPI 應用程式、設定 CORS，提供註冊、登入、目前使用者與管理者使用者清單 API |
| `workspace.py` | 提供角色工作區、車主軌跡查詢、廠商申請與主管審核 API |
| `database.py` | 載入環境設定，建立 SQLAlchemy engine、session 與 ORM Base |
| `models.py` | 定義角色及所有 SQLAlchemy ORM 資料表 |
| `schemas.py` | 定義註冊、使用者與 JWT 回應的 Pydantic schema |
| `auth.py` | 處理 bcrypt 密碼雜湊、密碼比對、JWT 建立與驗證 |
| `dependencies.py` | 提供資料庫 session、目前使用者與角色限制 dependency |
| `requirements.txt` | 後端及資料處理所需的 Python 套件版本 |
| `.env.example` | 本機環境變數範本，不包含實際密碼或金鑰 |
| `migrations/` | 已有資料庫的結構調整 SQL |

資料表建立入口位於專案根目錄的 `scripts/create_table.py`。

## 身份驗證與授權

公開註冊固定建立 `visitor` 身份，請求不能自行指定角色或帳號啟用狀態。密碼使用 bcrypt cost factor 12 雜湊，資料庫只保存雜湊結果。

登入成功後，後端簽發短效期 HS256 JWT。JWT 保存使用者 ID，包含 `iat`、`exp`、`iss` 與 `aud`。每次存取受保護 API 時，後端會：

1. 驗證 JWT 簽章、期限、issuer、audience 與必要 claims。
2. 使用 JWT 中的使用者 ID 重新查詢資料庫。
3. 確認帳號仍存在且處於啟用狀態。
4. 從資料庫讀取目前角色，執行 API 的角色限制。

目前角色包括：

```text
owner
visitor
vendor
supervisor_a
supervisor_b
admin
researcher
police
```

## API

| Method | Path | 權限 | 目前行為 |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | 公開 | 驗證 username、密碼與啟用狀態，回傳 Bearer JWT |
| `GET` | `/public/traffic-range` | 公開 | 回傳加密軌跡的全域最早與最晚時間 |
| `GET` | `/public/average-speed` | 公開 | 依時間回傳唯一的整體平均速度欄位 |
| `GET` | `/auth/me` | 已登入 | 回傳資料庫中的目前帳號與角色 |
| `GET` | `/users` | `admin` | 分頁列出帳號，單次最多 100 筆 |
| `GET` | `/workspace` | 已登入 | 依角色回傳工作區標籤及目前可用資料 |
| `GET` | `/workspace/trajectories` | `owner` | 依輸入車牌與選填時間下載模糊位置或速度 CSV |
| `GET` | `/workspace/vendor/trajectories` | `vendor` | 依車牌與必填時間下載模糊位置或精準速度 CSV |
| `POST` | `/workspace/requests` | `vendor` | 提交資料使用目的 |
| `POST` | `/workspace/requests/{request_id}/decision` | `supervisor_a`、`supervisor_b` | 記錄該主管的核准或拒絕決定 |

`GET /workspace` 目前依角色回傳以下資料：

- 車主：帳號綁定的車輛清單。
- 舊訪客帳號：只回傳公開訪客頁面提示，不提供統計資料。
- 合作廠商：自己的最近 100 筆申請；若存在雙主管核准的申請，另回傳整體與每日交通統計。
- 主管 A、主管 B：最近 100 筆資料申請。
- 管理者：帳號、軌跡與申請數量，以及最近 100 個帳號的基本狀態。
- 交通研究者、警方：目前回傳角色標籤、主要任務與狀態說明。

車主軌跡查詢接收 `plate`、`data_type`，以及選填的 `start`、`end`。後端由輸入車牌計算 `plate_lookup`，確認 `vehicle_ownerships` 中的所有權，再篩選 `encrypted_trajectories`。`data_type=location` 會在記憶體副本中依時間間隔切分行程，每趟首尾至少移除 200～500 公尺及 1 分鐘；每趟行程的緯度與經度各使用一個由伺服器密鑰穩定產生、介於 `±0.0005°` 的固定偏移。相同資料重複下載會得到相同結果，避免利用多次亂數輸出取平均；同一趟行程採固定偏移，以保留軌跡的相對移動。位置資料先對完整行程套用 PETs，再依 `start`、`end` 篩選，避免以時間切割查詢繞過起訖點遮蔽。`data_type=speed` 只解密速度並輸出 10 km/h 區間。CSV 保留精確時間，但不包含原始位置、上下限、精確速度、車牌密文或其他密文欄位；處理結果不會回寫資料庫。

合作廠商軌跡端點要求 `vendor` 角色、車牌、開始時間、結束時間及資料類型。模糊位置使用獨立於車主的固定偏移，精準速度只解密 `speed_enc`；輸出不包含任何車輛識別或密文。目前這個端點尚未檢查左側資料申請與主管核准狀態。

公開平均速度會先依 `(plate_lookup, timestamp)` 去除重複模擬紀錄，計算每台車在所選時間內的平均速度，再平均所有車輛的結果。回應只包含 `average_speed_kmh`；少於三台車時回傳 `null`，不公開車輛數、單車速度、位置、軌跡或密文。

資料申請分別保存主管 A 與主管 B 的決定。任一主管拒絕時狀態為 `rejected`；兩者都核准時為 `approved`；其他情況為 `pending`。同一主管不能重複修改已記錄的決定。

## 資料模型

所有登入身份共用 `users`，角色特有的資料保存在個別業務表，不為每個角色建立重複的帳號表。

| 資料表 | 用途 |
| --- | --- |
| `users` | 登入帳號、密碼雜湊、角色、啟用狀態與建立時間 |
| `vehicles` | 不透明內部車輛 ID、車牌 HMAC 查詢碼與建立時間，不保存車牌明文 |
| `vehicle_ownerships` | 車主帳號與車輛的唯一綁定關係 |
| `encrypted_trajectories` | 車牌、位置與速度分欄加密後的軌跡資料，時間保持明文 |
| `data_requests` | 廠商使用目的及主管 A、B 的獨立決定與審核者 |

`models.py` 是資料表結構的唯一 ORM 定義來源。`create_all()` 只建立缺少的資料表，不會修改既有欄位或刪除資料；既有資料表的結構變更使用 `migrations/` 中的 SQL。

## 環境設定

先從範本建立本機設定：

```bash
cp backend/.env.example backend/.env
```

後端使用以下環境變數：

| 變數 | 用途 |
| --- | --- |
| `DB_HOST` | MySQL 主機，預設 `127.0.0.1` |
| `DB_PORT` | MySQL 埠，預設 `3306` |
| `DB_NAME` | MySQL 資料庫名稱 |
| `DB_USER` | 專案使用的 MySQL 帳號 |
| `DB_PASSWORD` | MySQL 密碼 |
| `JWT_SECRET` | JWT 簽章秘密，至少 32 UTF-8 bytes |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 有效分鐘數，允許 1 至 60 |
| `CORS_ORIGINS` | 允許的前端 origin，以逗號分隔，不接受 `*` |

實際的 `backend/.env` 已被 Git 忽略，不應提交。

## 建表與啟動

在專案根目錄執行：

```bash
source .venv/bin/activate
python scripts/create_table.py
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

若要讓 VirtualBox 外的主機透過連接埠轉送存取，可將啟動參數改為 `--host 0.0.0.0`。

API 文件位於：

```text
http://127.0.0.1:8000/docs
```

可使用以下指令只檢查 MySQL 連線：

```bash
python -m backend.database
```

成功時會顯示 `MySQL connection succeeded.`，此檢查不會建立或修改資料表。
