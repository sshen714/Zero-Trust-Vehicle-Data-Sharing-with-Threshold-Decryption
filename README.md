# 零信任車輛資料分享

[後端套件與登入流程說明](docs/backend-packages.md)
[前端啟動]python3 -m http.server 5500 --bind 127.0.0.1 --directory frontend
[接著在瀏覽器開啟：]http://127.0.0.1:5500/login.html

# 零信任車輛資料分享

本專案包含前端登入介面、FastAPI 後端、MySQL 資料庫，以及車輛軌跡模擬程式。

後端套件、登入流程、JWT、bcrypt、SQLAlchemy、ORM 與 API 架構的詳細說明請閱讀：

- [後端套件與登入流程說明](docs/backend-packages.md)

本 README 只保留專案第一次啟動時需要的操作，不重複後端文件內容。

---

## 1. 建立 MySQL Database

進入 MySQL：

```bash
sudo mysql
```

建立專案資料庫：

```sql
CREATE DATABASE zero_trust_vehicle
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
```

確認：

```sql
SHOW DATABASES;
```

應該可以看到：

```text
zero_trust_vehicle
```

---

## 2. 建立專案 MySQL 帳號

建立一個專門給此專案使用的 MySQL 帳號：

```sql
CREATE USER 'vehicle_app'@'localhost'
IDENTIFIED BY '你的密碼';
```

授予 `zero_trust_vehicle` 的基本讀寫與建表權限：

```sql
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE
ON zero_trust_vehicle.*
TO 'vehicle_app'@'localhost';
```

套用權限：

```sql
FLUSH PRIVILEGES;
```

確認權限：

```sql
SHOW GRANTS FOR 'vehicle_app'@'localhost';
```

完成後離開 MySQL：

```sql
EXIT;
```

> `backend/.env` 的設定方式與資料庫連線架構請參考 `docs/backend-packages.md`，此處不重複說明。

---

## 3. 執行車輛模擬資料

確認後端環境與 MySQL 連線已設定完成後，在專案根目錄執行：

```bash
source .venv/bin/activate
python3 script/simulation_data.py
```

模擬程式會將資料直接寫入：

```text
Database: zero_trust_vehicle
Table: raw_trajectories
```

成功時會看到類似：

```text
成功寫入 3412 筆資料到 MySQL：raw_trajectories
```

### 確認資料

進入 MySQL：

```bash
sudo mysql
```

執行：

```sql
USE zero_trust_vehicle;

SHOW TABLES;

SELECT * FROM raw_trajectories LIMIT 10;

SELECT COUNT(*) FROM raw_trajectories;
```

---

## 4. 啟動前端

在專案根目錄執行：

```bash
python3 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

接著在瀏覽器開啟：

```text
http://127.0.0.1:5500/login.html
```

---

## 專案資料流

```text
simulation_data.py
        ↓
backend/database.py
        ↓
MySQL
        ↓
zero_trust_vehicle.raw_trajectories
```

後端登入、JWT、使用者模型、API 與權限設計請統一參考：

- [docs/backend-packages.md](docs/backend-packages.md)
