# Dynamic Adaptive AI Agent Workflow

以多渠道行銷為驗證情境的自適應 AI Agent 工作流程原型。

## 專案結構

```text
Dynamic-Adaptive-AI-Agent-Workflow/
├── frontend/          # 使用者操作介面（尚未實作）
├── backend/           # FastAPI 後端
│   ├── app/           # API、資料庫連線與資料模型
│   ├── requirements.txt
│   ├── .env.example   # 後端環境設定範本
│   └── .env           # 本機後端設定，不納入 Git
├── docs/
│   └── plans/         # 計畫書 PDF 與 Word 文件
└── README.md
```

前端負責使用者操作，後端負責 API、Agent 工作流程與資料庫存取。
目前已建立後端骨架，前端尚未實作。Neon 連線資訊放在 `backend/.env`；未來前端需要的環境設定放在 `frontend/.env`，各自管理。

## 目前基礎架構

- FastAPI：後端 API
- Neon PostgreSQL：保存 Goal、Strategy、Execution 與版本紀錄
- Python 虛擬環境：直接在本機啟動後端，不需要 Docker

## 啟動方式

需要 Python 3.11 以上版本，以及一個 Neon 專案。

1. 在 Neon 建立專案，開啟 **Connect** 視窗並複製 PostgreSQL 連線字串。
2. 在 `backend/.env` 填入連線字串（尚未存在時可從專案根目錄在 CMD 執行 `if not exist backend\.env copy backend\.env.example backend\.env`）：

   ```dotenv
   DATABASE_URL=postgresql://USER:PASSWORD@HOST.neon.tech/neondb?sslmode=require
   ```

   使用 Neon 提供的完整字串，保留其 SSL 等查詢參數。程式會自動使用 psycopg 驅動程式；`.env` 已排除於 Git 追蹤。

3. 在專案根目錄開啟 Windows 命令提示字元（CMD），執行：

   ```bat
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
   ```

4. 開啟 API 文件：<http://localhost:8000/docs>
5. 檢查服務：<http://localhost:8000/health>，應回傳 `{"status":"ok","database":"connected"}`。

啟動時會在 Neon 自動建立目前的資料表，因此需先填入有效的連線字串。按 `Ctrl+C` 可停止後端。後續啟動只需執行上述最後一行。

Neon 連線說明：<https://neon.com/docs/get-started/connect-neon>

## 資料模型

目前先建立持續改善循環的核心資料：

`Goal → Strategy(version) → Execution → Result`

下一步會加入 API endpoints、資料庫 migration、Agent orchestration、人工確認節點與測試資料。

