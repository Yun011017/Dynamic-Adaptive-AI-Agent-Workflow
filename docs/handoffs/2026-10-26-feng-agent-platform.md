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

## 已知限制與下一步

`POST /agent/runs` 目前同步完成一個短且無外部副作用的測試圖。下一位若要接真實模型，應先將 `agent_lab` 的互動式 graph 改為可注入 provider 的背景 worker；由 worker 持有模型 API key，並在 Neon 保存 job/checkpoint。不要把長時間模型呼叫、人工審核等待或發文動作留在 FastAPI HTTP request 裡。
