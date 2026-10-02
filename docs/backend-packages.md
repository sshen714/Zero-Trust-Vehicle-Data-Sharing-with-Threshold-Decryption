# 後端套件與登入流程說明

本文件說明第一階段登入系統需要的 Python 套件，以及它們如何配合前端與 MySQL。技術架構為 FastAPI、MySQL、SQLAlchemy、bcrypt 與 JWT，不使用 Docker。

目前專案已建立前端登入頁、CSS、JavaScript、Python 虛擬環境與資料庫連線模組。登入 API 仍會依照本文件後面的順序逐步完成。

## 1. 套件各自負責什麼

| 套件 | 主要用途 | 專案中的例子 |
| --- | --- | --- |
| FastAPI | 建立 HTTP API，接收請求、驗證輸入並回傳資料 | 提供 `/auth/register`、`/auth/login`、`/auth/me` |
| Uvicorn | ASGI 伺服器，負責運行 FastAPI 應用程式 | 監聽本機 8000 埠，接收瀏覽器的 HTTP 請求 |
| SQLAlchemy | ORM 與資料庫操作工具，以 Python 類別對應資料表 | 用 `User` 類別表示使用者，查詢帳號或新增使用者 |
| PyMySQL | Python 與 MySQL 通訊的資料庫驅動 | SQLAlchemy 透過它把 SQL 送到 MySQL，取得查詢結果 |
| bcrypt | 密碼雜湊與比對 | 註冊時產生 `hashed_password`，登入時比對密碼 |
| PyJWT | JWT 的編碼、簽章與驗證 | 登入成功後發行 token，後續請求驗證簽章與期限 |
| python-dotenv | 將 `.env` 的設定載入環境變數 | 載入資料庫帳號、密碼與 JWT Secret |
| python-multipart | 提供 FastAPI 解析表單資料所需的支援 | 解析登入表單的 `username` 與 `password` |
| Pydantic[email] | 資料驗證與格式定義，加上 Email 驗證依賴 | 驗證註冊輸入，定義不包含密碼雜湊的回應 |

FastAPI 本身使用 Pydantic；`[email]` 表示安裝 Pydantic 時一併加入 Email 驗證需要的額外套件。

## 2. FastAPI 與 Uvicorn 的差別

FastAPI 定義「收到某個請求時要做什麼」，例如收到登入請求後查詢帳號、比對密碼。Uvicorn 負責啟動這個應用程式並接受網路連線。

後端建立完成後，啟動指令預計如下：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

- `backend.main:app`：使用 `backend/main.py` 中的 `app` 應用程式。
- `--host 127.0.0.1`：只接受本機連線。
- `--port 8000`：使用 8000 埠。
- `--reload`：開發時，程式修改後自動重新載入。

目前尚未建立 `backend/main.py`，因此此指令要等後端完成後才能執行。

## 3. SQLAlchemy、PyMySQL 與 MySQL 的關係

資料庫存取順序如下：

```text
FastAPI 中的 Python 程式
        ↓
SQLAlchemy：組織查詢與管理資料庫 session
        ↓
PyMySQL：傳送 SQL 與接收結果
        ↓
MySQL Server：實際儲存使用者資料
```

SQLAlchemy 與 PyMySQL 都是 Python 套件，MySQL Server 則是獨立執行的資料庫服務。安裝 Python 套件不會自動安裝 MySQL Server，也不代表資料庫、帳號與權限已經設定完成。

ORM 可以減少手寫 SQL 的需求，但仍需要正確設定資料表、連線與資料庫權限。

### `backend/database.py` 的用途

`backend/database.py` 是後端執行期間持續使用的正式程式，不是安裝完成後即可刪除的設定腳本。之後的 ORM 模型、登入 API 與權限檢查都會透過它存取 MySQL。

它目前負責：

- 自動讀取 `backend/.env`。如果作業系統已提供同名環境變數，系統環境變數優先，方便日後部署。
- 檢查 `DB_USER`、`DB_PASSWORD` 與 `DB_NAME` 等必要設定，並拒絕空值及尚未替換的 `REPLACE_` 佔位值。
- 檢查 `DB_PORT` 是介於 1 到 65535 的整數。
- 使用 SQLAlchemy 的 `URL.create()` 組合資料庫 URL，安全處理資料庫密碼中的特殊字元，避免手動拼接 URL 時發生編碼錯誤。
- 建立 SQLAlchemy MySQL engine，並指定 PyMySQL 驅動及 `utf8mb4` 字元集。
- 建立 `SessionLocal`，讓每個 FastAPI 請求取得自己的資料庫 session；請求結束時由 context manager 關閉 session。
- 提供 ORM 模型共用的 `Base`，後續的 `User` 等資料表模型都會繼承它。
- 啟用 `pool_pre_ping=True`，從連線池取出連線時先確認連線仍有效，降低 MySQL 關閉閒置連線後出現失效連線的機率。
- 設定 `pool_recycle=1800`，使用滿 30 分鐘的連線會在下次取用時重建。
- 提供 `check_database_connection()`，以無副作用的 `SELECT 1` 測試連線。

可在專案根目錄執行以下指令測試：

```bash
source .venv/bin/activate
python -m backend.database
```

成功時會顯示：

```text
MySQL connection succeeded.
```

這個測試只確認連線和帳號權限足以執行基本查詢，不會建立、修改或刪除資料表。

### `backend/models.py` 與 `users` 資料表

`backend/models.py` 使用 SQLAlchemy ORM 定義使用者模型。它繼承 `database.py` 提供的 `Base`，讓 SQLAlchemy 知道 Python 的 `User` 類別對應 MySQL 的 `users` 資料表。

| 欄位 | 型別與限制 | 用途 |
| --- | --- | --- |
| `id` | 整數、主鍵、自動遞增 | 使用者的內部唯一識別值，也是 JWT 預計使用的 subject |
| `username` | 最多 50 字元、唯一、索引、不可為空 | 登入帳號 |
| `email` | 最多 254 字元、唯一、索引、不可為空 | 使用者 Email |
| `hashed_password` | 最多 255 字元、不可為空 | 儲存 bcrypt 雜湊，絕不儲存明文密碼 |
| `role` | MySQL ENUM、不可為空、預設 `visitor` | 後端授權時使用的目前角色 |
| `is_active` | 布林值、不可為空、預設啟用 | 停權時設為 false，受保護 API 將拒絕存取 |
| `created_at` | 日期時間、不可為空、由資料庫產生 | 記錄帳號建立時間 |

角色由 `Role` 列舉集中定義，共有 `owner`、`visitor`、`vendor`、`supervisor_a`、`supervisor_b`、`admin`。公開註冊 API 日後會固定建立 `visitor`，不能接受前端指定角色。

`models.py` 目前只描述資料表結構。匯入這個檔案不會自行建立資料表；建表會在 FastAPI 啟動流程加入，讓每一步可以分開檢查。正式系統後續若要修改既有資料表結構，應加入資料庫 migration 工具，而不是只修改 ORM 類別。

### `backend/schemas.py` 的用途

`backend/schemas.py` 使用 Pydantic 定義 API 可以接收與回傳的資料形狀。ORM 模型描述資料庫欄位，schema 則是 API 邊界的驗證規則；兩者用途不同。

目前包含三個 schema：

| Schema | 用途 |
| --- | --- |
| `RegisterRequest` | 驗證公開註冊時收到的帳號、Email 與密碼 |
| `UserResponse` | 回傳安全的使用者資料，不包含密碼或 `hashed_password` |
| `TokenResponse` | 登入成功後回傳 JWT 類型與有效秒數 |

`RegisterRequest` 的規則如下：

- `username` 長度為 3–50，只接受英文字母、數字、底線、句點與連字號。
- `email` 必須是有效 Email，最長 254 字元。
- `password` 至少 12 字元，最多 72 字元，而且 UTF-8 編碼後不能超過 bcrypt 的 72 bytes 上限。
- 未定義的額外欄位會被拒絕，所以公開註冊不能夾帶 `role` 或 `is_active`。
- 帳號前後的空白會清除；密碼內容不會被修改。

`UserResponse` 開啟 `from_attributes`，因此可以從 SQLAlchemy `User` 物件建立回應。它只列出允許離開後端的欄位，刻意沒有 `password` 與 `hashed_password`。

`TokenResponse` 將 `token_type` 固定預設為 `bearer`，並要求 `expires_in` 是大於零的秒數。JWT 的實際產生與驗證會在後續的 `auth.py` 實作。

### `backend/auth.py` 的用途

`backend/auth.py` 集中處理密碼與 JWT，避免登入 API 自行重複實作安全細節。

密碼處理包含：

- `hash_password()` 使用 bcrypt cost factor 12 和每次自動產生的隨機 salt 建立雜湊。
- `verify_password()` 比對輸入密碼與資料庫中的 bcrypt 雜湊；損壞的雜湊或超過長度的輸入會回傳 false，不會讓登入 API 崩潰。
- `password_bytes()` 以 UTF-8 編碼密碼並限制最多 72 bytes，避免 bcrypt 靜默截斷。
- `DUMMY_PASSWORD_HASH` 讓不存在的帳號也執行 bcrypt 比對，降低透過回應時間判斷帳號是否存在的風險。

JWT 處理包含：

- JWT Secret 從環境變數取得，且必須至少 32 UTF-8 bytes。
- 簽章演算法固定為 `HS256`，驗證時只允許此演算法，不能接受 token 自行宣告其他演算法。
- access token 包含使用者 ID `sub`、簽發時間 `iat`、到期時間 `exp`、簽發者 `iss` 與使用對象 `aud`。
- `ACCESS_TOKEN_EXPIRE_MINUTES` 必須是 1–60 的整數，目前範本預設為 15 分鐘。
- `decode_access_token()` 要求所有必要 claims 存在，並驗證簽章、期限、issuer 和 audience；失敗時由後續 API 統一轉為 HTTP 401。

JWT 只保存使用者 ID，不保存密碼或角色。受保護 API 驗證 JWT 後，仍會用使用者 ID 重新查詢資料庫，以取得目前的角色與停權狀態。

## 4. bcrypt 如何處理密碼

註冊時，後端將密碼交給 bcrypt，產生包含隨機鹽值與計算成本資訊的雜湊，再存入資料庫。相同密碼可以產生不同的雜湊。

登入時，bcrypt 使用輸入的密碼與資料庫中的雜湊進行比對。雜湊不是可還原的加密，後端不需要也不應還原原始密碼。

實作時會遵守：

- 不儲存明文密碼，也不把密碼寫入日誌。
- 使用 bcrypt 自動產生的隨機鹽值。
- bcrypt 的輸入上限為 72 bytes；超出上限的密碼會明確拒絕，避免截斷。
- 中文等字元可能占用多個 UTF-8 bytes，因此字元數不等於 bytes 數。

## 5. JWT 與 PyJWT 的用途

JWT 是登入憑證的一種格式，PyJWT 是處理這個格式的 Python 套件。

登入成功後，後端會發行帶有使用者 ID、簽發時間與到期時間等資訊的 JWT。前端暫存 token，之後透過 HTTP 標頭送出：

```http
Authorization: Bearer <JWT>
```

後端必須驗證簽章、允許的演算法與有效期限，才能使用 token 中的身分資訊。

一般簽章 JWT 的內容可被讀取，簽章用於偵測內容是否遭修改，並不會隱藏內容。因此不能把密碼、資料庫憑證或其他敏感秘密放入 JWT。

JWT Secret 是後端用來簽章與驗證的秘密值，必須由環境變數取得，不能放在前端或提交到 Git。

## 6. 註冊與登入流程

### 註冊

1. 前端送出帳號、Email 與密碼至 `POST /auth/register`。
2. FastAPI 與 Pydantic 驗證輸入格式。
3. SQLAlchemy 透過 PyMySQL 查詢帳號或 Email 是否已存在。
4. bcrypt 產生密碼雜湊。
5. 後端建立使用者，初始角色固定為 `visitor`。
6. 回傳安全的使用者資訊，不包含密碼與密碼雜湊。

目前前端只有登入表單，註冊介面會在後續步驟加入。

### 登入

1. 前端以表單格式送出帳號與密碼至 `POST /auth/login`。
2. Uvicorn 接收 HTTP 請求，交由 FastAPI 處理。
3. 後端透過 SQLAlchemy 與 PyMySQL 查詢使用者。
4. bcrypt 比對密碼，後端同時確認帳號是否啟用。
5. 驗證成功後，PyJWT 產生有期限的 JWT。
6. 前端將 JWT 暫存於 `sessionStorage`。
7. 前端帶著 JWT 呼叫 `GET /auth/me`。
8. 後端驗證 JWT，重新查詢使用者狀態與角色，再回傳資料供前端顯示。

`sessionStorage` 通常隨分頁工作階段結束而清除，但瀏覽器工作階段還原可能保留資料。同源 JavaScript 可以讀取它，因此仍需防範 XSS。清除瀏覽器中的 token 不會自動撤銷其他地方已複製的 token。

## 7. 如何落實第一階段的零信任概念

不能因為前端顯示「登入成功」就允許存取。每個受保護 API 都必須在後端重新檢查：

1. 是否提供 JWT。
2. JWT 簽章與驗證資訊是否有效，是否已過期。
3. JWT 對應的使用者是否仍存在。
4. 使用者目前是否啟用。
5. 資料庫中的目前角色是否具備操作權限。

角色必須從資料庫取得，不能相信前端傳入的角色，也不能只靠隱藏管理員按鈕來保護 API。

初始角色包含 `owner`、`visitor`、`vendor`、`supervisor_a`、`supervisor_b`、`admin`。第一階段只示範所有已登入且啟用的使用者能查看自己的資料，只有 `admin` 能查看使用者清單。

## 8. 設定與套件清單放在哪裡

| 檔案 | 用途 |
| --- | --- |
| `backend/requirements.txt` | 列出需要安裝的 Python 套件與版本限制 |
| `backend/.env.example` | 提供設定名稱與佔位值，可提交到 Git |
| `backend/.env` | 本機實際憑證設定，不可提交到 Git |
| `backend/database.py` | 讀取設定，建立 SQLAlchemy engine 與 session |

`.env` 本身不是加密儲存；需要限制檔案存取權限，並透過 `.gitignore` 排除。套件安裝成功也不代表資料庫可連線，後續仍需分別確認環境變數、MySQL 服務、資料庫帳號與權限。

## 9. 接下來的實作順序

為方便逐步檢查，接下來會分次完成：

1. 建立 `backend/requirements.txt`，準備虛擬環境並安裝套件。
2. 建立 `.gitignore` 與 `backend/.env.example`。
3. 設定本機 MySQL 資料庫與帳號，再設定實際環境變數。
4. 建立 `backend/database.py` 與連線驗證。
5. 建立使用者 ORM 與輸入、輸出 schema。
6. 加入 bcrypt、JWT 與後端權限檢查。
7. 建立 API、CORS，串接現有前端並測試。

第一階段不整合 CarSimulatorWithCAN，也不實作車牌假名化、位置隱私、分欄位加密、雙人核准或 Threshold Decryption。
