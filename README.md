# 零信任車輛資料分享

本專案包含前端登入介面、FastAPI 後端、MySQL 資料庫，以及車輛軌跡模擬程式。

後端套件、登入流程、JWT、bcrypt、SQLAlchemy、ORM 與 API 架構的詳細說明請閱讀：

- [後端套件與登入流程說明](docs/backend-packages.md)

## 1. Clone 後安裝 Python 3.11 與專案套件

本專案使用 Python 3.11。`.venv/` 是每位開發者在自己電腦建立的虛擬環境，不會提交到 GitHub。若 Ubuntu 內建的是其他 Python 版本，可用 `uv` 安裝獨立的 Python 3.11，不會更改系統 Python。

先安裝 Git、curl 與 MySQL Server（若尚未安裝）：

```bash
sudo apt update
sudo apt install git curl mysql-server
```

從 GitHub 取得專案並進入資料夾：

```bash
git clone <GitHub repository URL>
cd Zero-Trust-Vehicle-Data-Sharing-with-Threshold-Decryption
```

安裝 `uv`，並讓目前的 Bash 終端機找到它：

```bash
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-installer.sh
sh /tmp/uv-installer.sh
source "$HOME/.local/bin/env"
```

使用 `uv` 安裝 Python 3.11，並建立包含 pip 的虛擬環境：

```bash
uv python install 3.11
uv venv --seed --python 3.11 .venv
source .venv/bin/activate
```

安裝 Python 套件：

```bash
python --version
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

`python --version` 應顯示 Python 3.11.x。安裝過程若出現錯誤，先確認使用的是虛擬環境中的 Python：

```bash
which python
```

路徑應指向專案的 `.venv/bin/python`。往後每次開啟新的終端機，都在專案根目錄重新執行：

```bash
source .venv/bin/activate
```

若先前留下建立失敗的 `.venv`，先確認其中沒有要保留的資料，再移除並重建：

```bash
rm -r .venv
uv venv --seed --python 3.11 .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

Python 版本管理說明可參考 [uv 官方 Python 安裝文件](https://docs.astral.sh/uv/guides/install-python/)。

## 2. 建立環境設定

每位開發者需要建立自己的設定檔：

```bash
cp backend/.env.example backend/.env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

編輯 `backend/.env`，填入自己的 MySQL 密碼，並將指令產生的隨機值填入 `JWT_SECRET`。`backend/.env` 含有秘密且已被 Git 忽略，不可提交。

預設資料庫設定為：

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=vehicle_data_sharing
DB_USER=vehicle_app
```

## 3. 建立 MySQL Database 與專用帳號

進入 MySQL：

```bash
sudo mysql
```

在 MySQL 中執行以下 SQL，將密碼替換成 `backend/.env` 的 `DB_PASSWORD`：

```sql
CREATE DATABASE IF NOT EXISTS vehicle_data_sharing
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'vehicle_app'@'127.0.0.1'
IDENTIFIED BY '替換成你的 DB_PASSWORD';

ALTER USER 'vehicle_app'@'127.0.0.1'
IDENTIFIED BY '替換成你的 DB_PASSWORD';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, REFERENCES
ON vehicle_data_sharing.*
TO 'vehicle_app'@'127.0.0.1';

EXIT;
```

測試後端是否能使用 `.env` 連線：

```bash
source .venv/bin/activate
python -m backend.database
```

成功時會顯示：

```text
MySQL connection succeeded.
```

## 4. 啟動 FastAPI 後端

先在專案根目錄建立缺少的資料表：

```bash
source .venv/bin/activate
python scripts/create_table.py
```

建表入口統一放在 `scripts/create_table.py`，使用 `backend/.env` 的資料庫設定。
六張資料表的結構統一定義在 `backend/models.py`，建表腳本只負責執行建立。
腳本可重複執行，不會刪除資料，也不會變更既有欄位；欄位變更仍需 migration。

在專案根目錄執行：

```bash
source .venv/bin/activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

FastAPI 啟動時不再自動建立資料表。開啟 API 文件：

```text
http://127.0.0.1:8000/docs
```

可先使用 `POST /auth/register` 建立訪客帳號，再以 `POST /auth/login` 登入。`GET /auth/me` 需要 Bearer JWT；`GET /users` 僅允許 admin。停止後端時在終端機按 `Ctrl+C`。

## 5. 執行車輛模擬資料

確認虛擬環境、`backend/.env` 與 MySQL 連線都已設定完成後，在專案根目錄執行：

```bash
source .venv/bin/activate
python scripts/simulation_data.py
```

模擬程式先將車輛識別碼、位置與速度加密，再透過 `backend/database.py` 使用 `DB_NAME` 指定的資料庫，將結果寫入 `encrypted_trajectories`。`vehicles` 只保存不透明內部 ID 與 HMAC 查詢碼，不保存解密後的車牌。

可進入 MySQL 確認資料：

```bash
sudo mysql
```

```sql
USE vehicle_data_sharing;
SHOW TABLES;
SELECT id, plate_lookup, timestamp FROM encrypted_trajectories LIMIT 10;
SELECT COUNT(*) FROM encrypted_trajectories;
```

## 6. 啟動前端

在專案根目錄執行：

```bash
python3 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

接著在瀏覽器開啟：

```text
http://127.0.0.1:5500/login.html
```

登入成功後進入 `index.html` 導向頁，由 `GET /auth/me` 驗證 JWT 與身份後前往各自的 HTML 工作區。每個工作區也會驗證身份，身份不符時導向自己的頁面；登出會清除本分頁的登入憑證。

## 專案資料流

```text
scripts/simulation_data.py
        ↓
scripts/encryption.py
        ↓
backend/database.py
        ↓
MySQL
        ↓
vehicle_data_sharing.encrypted_trajectories
```

## 7. 公開訪客與七種登入身份

訪客不需要帳號或密碼，可從登入頁的「訪客」入口查看公開平均速度。其他身份使用本機測試帳號；帳號及密碼不隨 Git 提交，其他開發者 clone 專案後不會自動取得這些帳號。建立與驗證腳本已移除，`scripts/create_table.py` 只負責建表，不建立帳號。

密碼已隨機產生，儲存在專案根目錄的 `.demo-accounts.json`（僅本機使用，已被 Git 忽略）。每個帳號均使用自己的密碼；登入時填 username。

公開訪客頁位於 `frontend/visitor.html`；登入身份的介面分別位於 `frontend/owner.html`、`vendor.html`、`supervisor_a.html`、`supervisor_b.html`、`admin.html`、`researcher.html`、`police.html`。`index.html` 只負責登入後導頁，`app.js` 處理公開訪客查詢與登入身份驗證。

登入身份呼叫 `/auth/login` 與 `/auth/me` 驗證身份，角色頁會呼叫 `/workspace` 載入工作區基本資料。公開訪客頁不建立 session，只呼叫公開的時間範圍與平均速度 API。

| 身份 | 測試帳號 | 目前展示的畫面 |
| --- | --- | --- |
| 車主 | `demo_owner` | 輸入本人綁定車牌與選填時間，下載模糊位置或模糊速度 CSV |
| 訪客 | 不需帳號 | 選擇時間後只顯示所有車輛的整體平均速度 |
| 合作廠商 | `demo_vendor` | 依車牌與時間下載模糊位置或精準速度 CSV；左側申請流程尚未串接 |
| 主管 A | `demo_supervisor_a` | 依車牌與時間下載精準位置 CSV；左側精準速度申請尚未串接 |
| 主管 B | `demo_supervisor_b` | 速度查詢、主管 A OTP 申請與驗證入口（精準位置） |
| 系統管理者 | `demo_admin` | 帳號管理、服務與日誌、資料查詢及 OTP 入口 |
| 交通研究者 | `demo_researcher` | 依時間查詢研究資料，不顯示車牌查詢欄位 |
| 警方 | `demo_police` | 依車牌與時間查詢，以及 Email OTP 申請與驗證入口 |

操作方式：開啟 `http://127.0.0.1:5500/login.html`；訪客直接點選「訪客」，其他身份輸入測試帳號。車主可下載本人綁定車輛的模糊位置或速度 CSV；公開訪客只能查詢整體平均速度，沒有下載功能。

後端每次受保護請求都重新查詢帳號角色及啟用狀態。訪客不建立帳號，公開註冊 API 已移除。

此版本使用三把獨立的 AES-256-GCM 金鑰分欄保護車牌、位置與速度。授權設計不採用門檻解密或主管 A、B 共同重建金鑰：主管 A 負責精準位置的授權，主管 B 負責精準速度的授權，兩種資料各自驗證，不要求兩位主管同時同意。Email OTP、授權範圍、有效期限、撤銷流程與警方授權驗證仍待實作。資料筆數少時，彙總值仍不等同匿名化保證。

交通統計及每日分析使用 `encrypted_trajectories`，後端只在記憶體中解密計算所需欄位。車主使用 `GET /workspace/trajectories` 輸入車牌；後端計算 `plate_lookup`、檢查 `vehicle_ownerships`，再查詢加密軌跡。時間條件可省略，若提供則包含起訖端點且不帶時區。位置 CSV 會在記憶體副本中切分行程，每趟首尾至少移除 200～500 公尺及 1 分鐘；每趟行程的經緯度分別使用由伺服器密鑰穩定產生、介於 `±0.0005°` 的固定偏移，使近似軌跡保留相對移動且不公開上下限。時間篩選在 PETs 處理後才套用。速度 CSV 採 10 km/h 區間（不含上限）。處理過程不會回寫或修改 `encrypted_trajectories`。資料申請使用 `data_requests`，OTP 驗證狀態使用只保存雜湊的 `otp_challenges`。六張資料表統一定義於 `backend/models.py`，由 `scripts/create_table.py` 建立。

合作廠商使用 `GET /workspace/vendor/trajectories` 依車牌與必填時間範圍下載資料。位置 CSV 套用與車主分離的固定 PETs 偏移並去除行程首尾；速度 CSV 回傳解密後的精準速度。兩種 CSV 都不包含車牌、`plate_lookup` 或密文。目前只完成右側查詢下載，尚未強制連結左側申請與主管核准。

合作廠商左側已提供 OTP 模擬：建立位置申請時產生六位數 OTP，資料庫只保存同時綁定車牌與時間範圍的 HMAC-SHA256 雜湊、五分鐘期限、錯誤次數與使用狀態。驗證成功會立即下載核准條件的精準位置 CSV。Demo 期間 API 會回傳原始 OTP 供本機輸入測試，目前尚未寄送 Email。

主管 A 使用 `GET /workspace/supervisor-a/locations` 依車牌與必填時間範圍下載精準位置 CSV。端點只允許 `supervisor_a`，並且只解密位置；CSV 不包含車牌、`plate_lookup`、速度或密文。

主管 A 左側已提供精準速度 OTP 模擬。OTP 雜湊綁定車牌與時間範圍，五分鐘內可嘗試五次且只能成功使用一次；驗證成功後立即下載精準速度 CSV。Demo 期間 API 會回傳原始 OTP 供本機測試，目前尚未寄送 Email。

主管 B 使用 `GET /workspace/supervisor-b/speeds` 依車牌與必填時間範圍下載精準速度 CSV。端點只允許 `supervisor_b`，並且只解密速度；CSV 不包含車牌、`plate_lookup`、位置或密文。左側精準位置申請保留給後續 OTP 流程，目前尚未串接。

系統管理者使用 `GET /workspace/admin/trajectories` 依必填時間及車牌或完整速度範圍篩選資料。後端解密後套用速度條件，再輸出已去除行程首尾的模糊位置與 10 km/h 速度區間 CSV；CSV 不包含車牌、`plate_lookup`、精準位置、精準速度或密文。

交通研究者使用 `GET /workspace/researcher/trajectories` 依必填時間範圍下載研究 CSV。後端先對完整資料套用 `apply_researcher_pets()`，包含行程首尾去除、假名與靜默期、位置偏移、降低頻率、`coarsen_time()` 時間粗化及速度取整，再依時間範圍輸出；不提供車牌查詢或精準欄位。
