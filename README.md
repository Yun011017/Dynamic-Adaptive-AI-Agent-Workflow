# Dynamic Adaptive AI Agent Workflow

以社團多渠道行銷為驗證情境的自適應 AI Agent 工作流程原型。

## 目錄

```text
frontend/                      Next.js、React、Tailwind 使用者介面
backend/
  app/                         FastAPI、ORM、連線、基本 API
  meta_api_test/               Meta OAuth / Instagram API 獨立測試沙盒
  migrations/                  Alembic 版本化 schema
  scripts/manage.py            migration、seed、連線驗證
  tests/                       真實 PostgreSQL 隔離整合測試
  seed.sql                     可重複執行的虛構資料
  .env.example                 後端設定範本
  .env                         本機設定，不進 Git
.github/workflows/backend.yml  CI 與 development 部署
 docs/                         架構、驗收與計畫書
```

資料庫只使用 Neon PostgreSQL。前端設定放 `frontend/`，後端設定放 `backend/`。
Meta API 沙盒的設定獨立放在 `backend/meta_api_test/.env`，範本為同目錄的 `.env.example`；不要把 Meta 憑證放進一般 `backend/.env`。

## 本機啟動

需要 Python 3.11 或 3.12。以下指令都在終端機執行。

### 第一次初始化

第一次請在專案根目錄開啟 CMD，完成前後端初始化：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
if not exist backend\.env copy backend\.env.example backend\.env
if not exist frontend\.env copy frontend\.env.example frontend\.env
cd frontend
npm install
cd ..
```

在 Neon Connect 複製連線資訊後設定：

- `DATABASE_URL`：API 使用的 pooled 連線，保留 SSL 參數。
- `MIGRATION_DATABASE_URL`：同一 Neon database 的 direct 連線，migration 使用；可由 Neon Connect 關閉 pooling 取得。不能連到另一個 database。
- `PLATFORM_API_KEY`：至少 32 字元的隨機開發用金鑰；不設定則所有業務 API 停用，`/health` 仍可測試。
- `PLATFORM_WORKSPACE_SLUG=development`：金鑰只能存取此工作空間，不接受前端指定任意 workspace。

產生開發金鑰的 CMD 指令（將輸出貼入 `.env`，不要放入 Git／前端）：

```bat
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

設定好 `backend/.env` 後，執行一次資料庫初始化：

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m scripts.manage seed
..\.venv\Scripts\python.exe -m scripts.manage check
cd ..
```

### 平常啟動

已完成第一次初始化後，開啟兩個 CMD 視窗：一個啟動後端，一個啟動前端。

後端 CMD：

```bat
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端 CMD：

```bat
cd frontend
npm run dev
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就代表後端已啟動。開啟 [API 文件](http://localhost:8000/docs) 與 [健康檢查](http://localhost:8000/health)；`/health` 顯示 `ok` 代表 FastAPI 已連到 Neon。按 `Ctrl+C` 可停止對應的服務。

前端可建立 Agent 工作、查看背景 worker 的執行狀態與讀取完成結果。開啟 [http://localhost:3000](http://localhost:3000)，按右上角「連線設定」，填入：

- FastAPI URL：`http://127.0.0.1:8000`
- Development API key：`backend/.env` 的 `PLATFORM_API_KEY`

在 `/docs` 的 **Authorize** 同樣填入 `backend/.env` 的 `PLATFORM_API_KEY`，才能操作業務 API。

### 本機立即處理 Agent 工作（選用）

GitHub Actions 排程外，若要在本機立刻處理等待中的工作，可再開第三個 CMD：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

前端只會呼叫 FastAPI，不會直接連 Neon。開發用 API key 只存於目前瀏覽器分頁，關閉分頁後即清除。

## 部署

後端 FastAPI 已部署於 Vercel：
[https://dynamic-adaptive-ai-agent-workflow-api.vercel.app/](https://dynamic-adaptive-ai-agent-workflow-api.vercel.app/)

前端已部署至 Vercel：
[https://dynamic-adaptive-ai-agent-workflow.vercel.app/](https://dynamic-adaptive-ai-agent-workflow.vercel.app/)

## GitHub Actions Agent worker

[`agent-worker.yml`](.github/workflows/agent-worker.yml) 每次只處理一筆等待中的 Agent 工作後結束，不需要讓電腦持續開著。

前端建立工作後，資料會先以 `PENDING` 狀態寫入 Neon；GitHub Actions 每 5 分鐘檢查一次：

- 有 `PENDING` 工作：執行 Agent，並把結果與狀態寫回 Neon。
- 沒有工作：正常結束，不進行任何處理。

因此工作通常會在 0 至 5 分鐘內開始；GitHub 排程繁忙時可能更久。公開 repository 使用 GitHub 標準 runner 不收執行分鐘費用，詳見 [GitHub Actions 計費說明](https://docs.github.com/en/actions/concepts/billing-and-usage)。
