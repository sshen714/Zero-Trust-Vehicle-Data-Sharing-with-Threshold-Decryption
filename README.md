# 零信任車輛資料分享

本專案包含前端登入介面、FastAPI 後端、MySQL 資料庫，以及車輛軌跡模擬程式。

後端套件、登入流程、JWT、bcrypt、SQLAlchemy、ORM 與 API 架構的詳細說明請閱讀：

- [後端套件與登入流程說明](docs/backend-packages.md)

## 1. Clone 後建立 Python 虛擬環境

`.venv/` 是每位開發者電腦上的 Python 虛擬環境，不會提交到 GitHub。第一次 clone 專案後，請在專案根目錄執行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

成功啟用後，終端機提示字元前面會出現 `(.venv)`。可用以下指令確認：

```bash
which python
```

輸出路徑應指向目前專案中的 `.venv/bin/python`。每次開啟新的終端機後，都要在專案根目錄重新執行：

```bash
source .venv/bin/activate
```

如果建立 `.venv` 時顯示缺少 `ensurepip` 或 `venv`，Ubuntu 可先安裝：

```bash
sudo apt update
sudo apt install python3-venv
```

若錯誤訊息指定版本套件，例如 Python 3.8 的 `python3.8-venv`，請依訊息安裝：

```bash
sudo apt install python3.8-venv
```

刪除建立失敗的 `.venv`，再重新執行本節最前面的建立與安裝指令。

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

## 4. 執行車輛模擬資料

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

## 5. 啟動前端

在專案根目錄執行：

```bash
python3 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

接著在瀏覽器開啟：

```text
http://127.0.0.1:5500/login.html
```

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
