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

- `AGENT_PROVIDER=local`
- `AGENT_MODEL=deterministic-langgraph`

此階段不讀取模型 API key。`agent_lab/` 的 Gemini、OpenAI、Claude key 仍只透過其終端機提示輸入，不能提交 Git。

## 背景 Worker 與模型整合

- `POST /agent/runs` 建立 `PENDING` 工作並回傳 `202 Accepted`，不在 HTTP request 內執行模型。
- `backend/app/agent_worker.py` 使用 `FOR UPDATE SKIP LOCKED` 取得工作、標示 `RUNNING`、執行 LangGraph，最後寫回 `COMPLETED` 或 `FAILED`。
- `agent_run_checkpoints` 保存 `RUNNING` 與結束狀態；超過 `AGENT_RUN_LEASE_SECONDS` 的 `RUNNING` 工作可由另一個 worker 接手。
- 預設 `local` provider 不需 API key。Gemini、OpenAI、Claude 會由 worker 讀取自己的環境變數 key，並用與 `agent_lab` 相同的工具呼叫模式執行。

在 CMD 啟動 worker：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

## 已知限制與下一步

目前模型 graph 僅完成「讀取測試表單摘要 → 產生建議」。Agent Core 負責人仍需提供能等待並恢復人工審核的非互動式 graph；平台端再把該 graph 注入 worker。不要把長時間模型呼叫、審核等待或發文動作留在 FastAPI HTTP request 裡。
