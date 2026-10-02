# 後端套件與登入流程說明

本文件說明第一階段登入系統需要的 Python 套件，以及它們如何配合前端與 MySQL。技術架構為 FastAPI、MySQL、SQLAlchemy、bcrypt 與 JWT，不使用 Docker。

目前專案已建立前端登入頁、CSS 與 JavaScript；以下後端功能是接下來要逐步實作的內容。本文件不代表套件已安裝或後端已完成。

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
