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
四張資料表的結構統一定義在 `backend/models.py`，建表腳本只負責執行建立。
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

模擬程式透過 `backend/database.py` 使用 `DB_NAME` 指定的資料庫，並將資料寫入 `raw_trajectories` 資料表。

可進入 MySQL 確認資料：

```bash
sudo mysql
```

```sql
USE vehicle_data_sharing;
SHOW TABLES;
SELECT * FROM raw_trajectories LIMIT 10;
SELECT COUNT(*) FROM raw_trajectories;
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
backend/database.py
        ↓
MySQL
        ↓
vehicle_data_sharing.raw_trajectories
```

## 7. 八種身份與測試帳號

目前本機已建立八種身份的測試帳號。帳號及密碼不隨 Git 提交，其他開發者 clone 專案後不會自動取得這些帳號。建立與驗證腳本已移除，`scripts/create_table.py` 只負責建表，不建立帳號。

密碼已隨機產生，儲存在專案根目錄的 `.demo-accounts.json`（僅本機使用，已被 Git 忽略）。每個帳號均使用自己的密碼；登入時填 username。

八種身份的介面分別位於 `frontend/owner.html`、`visitor.html`、`vendor.html`、`supervisor_a.html`、`supervisor_b.html`、`admin.html`、`researcher.html`、`police.html`。`index.html` 只負責登入後導頁，`app.js` 處理共用登入驗證與展示按鈕，不產生角色畫面。

目前先製作八種身份的前端展示畫面。登入仍呼叫 `/auth/login` 與 `/auth/me` 驗證身份；工作區不呼叫 `/workspace`、歷史軌跡、申請或審核 API。畫面的資料權限文字是預定設計，並不表示 OTP、PETs 或查詢流程已完成。操作按鈕只顯示展示提示，不會查詢、上傳或儲存資料。

| 身份 | 測試帳號 | 目前展示的畫面 |
| --- | --- | --- |
| 車主 | `demo_owner` | 本人車牌唯讀欄位、查詢按鈕及結果空位，尚未串接資料 |
| 訪客 | `demo_visitor` | 時間區間查詢、車流量、平均速度、壅塞程度（統計值為空） |
| 合作廠商 | `demo_vendor` | 資料使用申請、核准資料分析、主管 A OTP 申請與驗證入口（精準位置） |
| 主管 A | `demo_supervisor_a` | 位置查詢、主管 B OTP 申請與驗證入口（精準速度） |
| 主管 B | `demo_supervisor_b` | 速度查詢、主管 A OTP 申請與驗證入口（精準位置） |
| 系統管理者 | `demo_admin` | 帳號管理、服務與日誌、資料查詢及 OTP 入口 |
| 交通研究者 | `demo_researcher` | 依時間查詢研究資料，不顯示車牌查詢欄位 |
| 警方 | `demo_police` | 依案件編號、車牌與時間查詢，以及案件 OTP 申請與驗證入口 |

操作方式：開啟 `http://127.0.0.1:5500/login.html`，登入不同身份的測試帳號查看畫面；切換身份時先登出。所有工作區操作均為介面展示，未串接業務資料。已有的後端 API 保留，後續再逐步接上。

後端每次請求都重新查詢帳號角色及啟用狀態。公開註冊仍固定建立訪客，不能由前端指定主管或管理者角色。

此版本為角色權限與雙人審核的第一階段：分析授權是帳號層級、無到期時間，只提供去除個別車輛識別的交通統計；研究者與警方查詢、其他身份的時間區間篩選與位置／速度模糊化、Email OTP、事故分析、正式的授權範圍／撤銷流程、門檻解密及網站維護操作尚未實作。資料筆數少時，彙總值仍不等同匿名化保證。

交通統計及每日分析使用既有的模擬資料表 `raw_trajectories`。後端工作區 API 依登入帳號從 `vehicle_ownerships` 取得綁定車輛，車主可使用 `GET /workspace/trajectories` 查詢自己的綁定車輛；起訖時間均包含端點，時間不帶時區且依資料庫記錄解讀，每頁 100 筆。時間保留原值、經緯度採 0.01° 區間、速度採 10 km/h 區間（皆不含上限），不回傳原始位置與速度。這是固定區間模糊化，並非差分隱私或門檻解密。資料申請使用 `data_requests`。四張資料表（含 `users`）統一定義於 `backend/models.py`，由 `scripts/create_table.py` 建立。
