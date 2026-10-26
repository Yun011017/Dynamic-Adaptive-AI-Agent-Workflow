# FastAPI Neon Agent 整合交接

## 完成內容

- 新增 `agent_runs` migration 與 ORM model，保存 run_id、輸入、輸出、狀態、錯誤、使用的 provider/model 與開始結束時間。
- 新增受 `PLATFORM_API_KEY` 保護的 `POST /agent/runs` 與 `GET /agent/runs/{run_id}`。
- 新增 `backend/app/agent_runner.py`，以 LangGraph 執行固定表單摘要到行銷建議的安全測試流程。
- 新增 PostgreSQL 整合測試，驗證 API 執行、資料庫保存與 run_id 查詢。

## 驗證方式

在專案根目錄使用 CMD：

```bat
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\python.exe -m unittest tests.test_platform -v
```

API 端點需在 `/docs` 的 Authorize 填入 `backend/.env` 的 `PLATFORM_API_KEY`。

## 環境設定

- 預設可使用 `AGENT_PROVIDER=local` 與 `AGENT_MODEL=deterministic-langgraph`，不呼叫外部模型。
- **目前本機的 `backend/.env` 已使用 Gemini provider 並完成真實模型驗證。**

`backend/.env` 不進 Git。已取得團隊共用 Gemini key 的成員，可直接在自己的 `backend/.env` 設定 Gemini provider 後使用；不需要再透過 `agent_lab/` 手動輸入。雲端 worker 則由管理者在 Secret／Environment Variables 設定同一把 key。任何 key 都不能提交 Git、貼到前端或寫進交接文件。

## 背景 Worker 與模型整合

- `POST /agent/runs` 建立 `PENDING` 工作並回傳 `202 Accepted`，不在 HTTP request 內執行模型。
- `backend/app/agent_worker.py` 使用 `FOR UPDATE SKIP LOCKED` 取得工作、標示 `RUNNING`、執行 LangGraph，最後寫回 `COMPLETED` 或 `FAILED`。
- `agent_run_checkpoints` 保存 `RUNNING` 與結束狀態；超過 `AGENT_RUN_LEASE_SECONDS` 的 `RUNNING` 工作可由另一個 worker 接手。
- 預設 `local` provider 不需 API key。Gemini、OpenAI、Claude 會由 worker 讀取自己的環境變數 key，並用與 `agent_lab` 相同的工具呼叫模式執行。
- 已用 Gemini worker 完成一次無外部副作用的 verification run：工具呼叫、Neon checkpoint 與 `COMPLETED` 結果均已確認。

在 CMD 啟動 worker：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

測試真實模型時，先在 `backend/.env` 選擇一個 provider、模型與對應 key：

```text
AGENT_PROVIDER=gemini
AGENT_MODEL=gemini-3.5-flash-lite
GOOGLE_API_KEY=你的 key
```

修改 `.env` 後，要重啟 worker。OpenAI 與 Claude 依序使用 `openai`／`OPENAI_API_KEY`、`claude`／`ANTHROPIC_API_KEY`。模型 key 不應進 Git、API request、資料庫 payload、log 或前端。

## 本機啟動方案

第一次使用時，依根目錄 README 建立 `.venv`、安裝 `backend/requirements-dev.txt`，設定 `backend/.env`，並完成 migration：

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m scripts.manage seed
..\.venv\Scripts\python.exe -m scripts.manage check
```

日常整合測試需要三個 CMD 視窗：

1. FastAPI：

```bat
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

2. Worker：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

3. Next.js 前端（第一次需先執行 `npm install`）：

```bat
cd frontend
if not exist .env copy .env.example .env
if not exist node_modules npm install
npm run dev
```

前端開啟 `http://localhost:3000`。開發時在「連線設定」填入 `http://127.0.0.1:8000` 與 `backend/.env` 的 `PLATFORM_API_KEY`。此 key 僅存在目前瀏覽器分頁；正式版應改為登入 session，不可自動傳給前端。

`FRONTEND_ORIGINS` 預設允許 `localhost`／`127.0.0.1` 的本機開發埠。若前端顯示「無法連線後端」，先在瀏覽器開啟 `http://127.0.0.1:8000/health`；顯示 `{"status":"ok","database":"connected"}` 後，再重新整理前端。worker 閒置時沒有輸出是正常現象，它只會在 Neon 出現 `PENDING` 工作時開始處理。

## 測試紀錄

- Neon migration 已套用至 `0004`；`scripts.manage check` 已驗證核心表與 seed chain。
- Gemini 背景 worker 已完成一次真實模型測試：工作從 `PENDING` 到 `COMPLETED`，輸出與 checkpoint 均已寫入 Neon。
- 前端已改為 React、Next.js App Router、Tailwind CSS；`npm run build` 已成功通過 production build。
- 前端手動驗證流程：設定連線 → 建立 Agent 工作 → 確認 `PENDING → RUNNING → COMPLETED`，並在「工作詳情」看到模型輸出。送出後新增工作表單會收起；選「建立下一筆工作」才會重新展開。
- 新增 `GET /agent/runs`，前端的「工作歷史紀錄」會直接讀取同一 workspace 已保存於 Neon 的工作，不限於目前頁面建立的項目。

整合測試需要能解析 Neon 網域的網路環境；若 `unittest` 出現 `getaddrinfo failed`，先確認本機網路／DNS，不要把它判定為 migration 或程式邏輯錯誤。

### 前端可直接使用的測試資料

在 `http://localhost:3000` 完成連線設定後，使用以下內容建立工作：

- 活動目標：`提高 3D 列印入門工作坊的報名完成率`
- 活動背景：`活動提供零基礎學生體驗建模與 3D 列印，報名頁已有訪客但完成填表比例偏低，希望用清楚的作品成果與流程說明降低參加門檻。`
- 建議渠道：`Google Forms`

送出後，右側應先出現工作卡，狀態依序為 `PENDING → RUNNING → COMPLETED`。選取該工作後，在「工作詳情」確認模型、run ID、完成時間與建議內容皆有顯示。若停在 `PENDING`，確認 worker CMD 視窗仍在執行；若顯示 `FAILED`，查看下方錯誤訊息與 worker 終端機輸出。

## 已知限制與下一步

目前模型 graph 僅完成「讀取測試表單摘要 → 產生建議」。Agent Core 負責人仍需提供能等待並恢復人工審核的非互動式 graph；平台端再把該 graph 注入 worker。不要把長時間模型呼叫、審核等待或發文動作留在 FastAPI HTTP request 裡。
