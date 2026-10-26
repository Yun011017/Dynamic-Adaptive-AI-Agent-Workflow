# GitHub Actions Agent Worker 部署與驗收交接

## 目前狀態

- GitHub `main` 已加入 `.github/workflows/agent-worker.yml`，以排程方式執行 worker，不需要常駐主機。
- Workflow 每 5 分鐘排程一次，使用 GitHub-hosted runner 執行 `python -m app.agent_worker --once`，每次最多處理一筆工作後結束。排程可能因 GitHub 忙碌而延遲；佇列有多筆工作時，每次執行只處理一筆。
- `ENABLE_AGENT_WORKER=true` 已設為 repository variable，定時執行已啟用；`workflow_dispatch` 可手動測試。
- GitHub Actions repository secrets 已存在 `NEON_DATABASE_URL` 與 `GOOGLE_API_KEY`。僅記錄名稱與存在狀態，不記錄或輸出其值。
- GitHub 上 `Process queued Agent work` 手動 workflow run 已成功完成，必要 secret 檢查與 worker 命令皆成功。該次記錄沒有顯示 `Processed Agent run: ...`，因此不能據此宣稱它實際處理過佇列工作或驗證過真實模型呼叫。

## Workflow 設定

Workflow 從 repository 根目錄的 `.github/workflows/agent-worker.yml` 讀取，使用：

- `NEON_DATABASE_URL`：GitHub Actions repository secret，供 worker 連接 Neon。
- `GOOGLE_API_KEY`：GitHub Actions repository secret，供 Gemini 模型呼叫。
- `ENABLE_AGENT_WORKER=true`：GitHub Actions repository variable，啟用 cron 排程。
- Provider/model 固定為 `gemini`／`gemini-3.5-flash-lite`；執行細節與超時值見 workflow 檔。

不得將 secret 值複製到 Git、文件、workflow 輸出或前端。若需更新憑證，應在 GitHub **Settings → Secrets and variables → Actions** 直接更換。

## 驗證紀錄與限制

- 本機以專案 `.venv` 執行 `python -m unittest discover -s tests -v`：`test_agent_runner` 通過；`test_platform` 因本機未提供隔離測試資料庫的 `DATABASE_URL` 而無法載入。不要拿正式 Neon 資料庫當測試資料庫。
- GitHub Actions 手動執行成功，但該次未處理到有記錄輸出的 run。需要再建立一筆明確可辨識的測試工作，確認 Neon 狀態確實由 `PENDING` 變成 `COMPLETED`，並在輸出看到 run ID；避免重複建立無法清理的正式資料。
- GitHub cron 的 5 分鐘間隔是排程頻率，不是執行時間保證；實際開始時間可能更久。若 backlog 超過一筆，worker 每次只取一筆，後續排程會繼續處理。
- Workflow 固定使用 Gemini，所以 `GOOGLE_API_KEY` 必須有效且具備模型呼叫額度。執行 Agent 可能產生模型 API 用量費用；GitHub runner 的費用依 repository 可用方案與使用量政策為準。
- 本機工作目錄可能有未追蹤的 `backend/.vscode/settings.json` 個人設定；不要納入部署提交。

## 下一步

1. 在前端建立一筆可識別的測試工作。
2. 到 GitHub **Actions → Process queued Agent work → Run workflow** 手動執行一次。
3. 確認該筆工作在前端或 Neon 管理介面完成 `PENDING → RUNNING → COMPLETED`，並檢查 Agent 輸出與 run ID。
4. 再觀察至少一次 `schedule` 事件，確認每 5 分鐘的自動排程也正常啟動。
5. 若 Vercel 前端尚未部署最新 main，檢查前端 Production deployment；此 worker workflow 不會部署 Vercel 前端。

## 對應版本

本次接手時本機與 `origin/main` 同步於 `c88e139`。本文件的更新另由後續文件提交記錄。
