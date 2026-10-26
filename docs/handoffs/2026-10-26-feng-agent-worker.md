# Agent 背景 Worker 交接

## 完成內容

- `POST /agent/runs` 現在只建立 `PENDING` 工作並回傳 `202 Accepted`，不在 FastAPI request 內等待 Agent。
- 新增 `backend/app/agent_worker.py`。worker 以 Neon 的 row lock 取得一筆待執行工作、標示 `RUNNING`、執行 LangGraph，最後寫回 `COMPLETED` 或 `FAILED`。
- worker 支援 `--once`，適合本機測試與之後的排程平台。
- PostgreSQL 整合測試驗證 API 建立工作、worker 執行，以及 run 結果查詢。

## 在 CMD 使用

先啟動 API：

```bat
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

再開另一個 CMD 視窗啟動 worker：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

## 下一位接手

目前 worker 呼叫的是無 API key 的 `backend/app/agent_runner.py` 測試圖。Agent Core 負責人應將 `agent_lab` 的 Gemini、OpenAI、Claude provider 改為可由 worker 呼叫的非互動介面；平台接手者再將其注入 worker。模型 key 僅放在 worker 環境變數，不能透過 API request、資料庫 payload、log 或前端傳遞。
