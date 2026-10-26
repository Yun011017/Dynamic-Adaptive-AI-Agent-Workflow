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

第一次才需要建立虛擬環境、安裝套件與建立設定檔：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
if not exist backend\.env copy backend\.env.example backend\.env
notepad backend\.env
```

在 Neon Connect 複製連線資訊後設定：

- `DATABASE_URL`：API 使用的 pooled 連線，保留 SSL 參數。
- `MIGRATION_DATABASE_URL`：同一 Neon database 的 direct 連線，migration 使用；可由 Neon Connect 關閉 pooling 取得。不能連到另一個 database。
- `PLATFORM_API_KEY`：至少 32 字元的隨機開發用金鑰；不設定則所有業務 API 停用，`/health` 仍可測試。
- `PLATFORM_WORKSPACE_SLUG=development`：金鑰只能存取此工作空間，不接受前端指定任意 workspace。
- `DB_POOL_MODE=null`：本機與 Vercel HTTP API 預設不保留應用連線池；獨立 worker 可設 `queue`。

產生開發金鑰的 CMD 指令（將輸出貼入 `.env`，不要放入 Git／前端）：

```bat
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

設定好 `.env` 後，執行一次資料庫初始化：

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m scripts.manage seed
..\.venv\Scripts\python.exe -m scripts.manage check
```

三個指令都沒有顯示錯誤後，再啟動後端：

```bat
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就代表後端已啟動。開啟 [API 文件](http://localhost:8000/docs) 與 [健康檢查](http://localhost:8000/health)。`/health` 顯示 `ok` 代表 FastAPI 已連到 Neon。按 `Ctrl+C` 停止後端。

### 平常啟動

已經做過第一次初始化時，只需開啟 cmd、進入專案後執行：

```bat
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

在 `/docs` 的 **Authorize** 填入 `.env` 的 `PLATFORM_API_KEY`，才能操作業務 API。

### 前端操作介面

前端可建立 Agent 工作、查看背景 worker 的執行狀態與讀取完成結果。請開啟第二個 CMD 視窗，第一次先安裝前端套件：

```bat
cd frontend
if not exist .env copy .env.example .env
npm install
npm run dev
```

之後只需執行：

```bat
cd frontend
npm run dev
```

開啟 [http://localhost:3000](http://localhost:3000)，按右上角「連線設定」，填入：

- FastAPI URL：`http://127.0.0.1:8000`
- Development API key：`backend/.env` 的 `PLATFORM_API_KEY`

若要讓工作實際由 Agent 處理，另開第三個 CMD 視窗：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

前端只會呼叫 FastAPI，不會直接連 Neon。開發用 API key 只存於目前瀏覽器分頁，關閉分頁後即清除。

各模組的專用設定、驗證紀錄與下一位接手事項，請閱讀 [`docs/handoffs/`](docs/handoffs/)；新增交接文件時不要覆蓋既有內容。

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

啟用前，到 GitHub repository 的 **Settings → Secrets and variables → Actions** 設定：

- Secret `NEON_DATABASE_URL`：Neon 的 `DATABASE_URL`。
- Secret `GOOGLE_API_KEY`：Gemini API key。
- Variable `ENABLE_AGENT_WORKER`：設為 `true`，才會啟用每 5 分鐘的排程。

可在 **Actions → Process queued Agent work → Run workflow** 手動執行一次來測試。只有信任的 repository 寫入者可修改 workflow；所有 key 都應維持在 GitHub Secrets，且已外露的 key 必須先旋轉後再設定。
