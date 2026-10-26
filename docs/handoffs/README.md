# 交接文件規則

每次完成可由下一位接手的工作時，在此目錄新增一份文件，不修改或覆蓋既有交接內容。

檔名使用 `YYYY-MM-DD-負責範圍.md`，例如 `2026-10-26-feng-agent-platform.md`。

每份交接至少包含：完成內容、驗證方式、環境變數與憑證位置、已知限制、下一位可直接開始的工作，以及對應 commit。

## 最新狀態

- [2026-10-26 GitHub Actions Agent Worker 部署與驗收](2026-10-26-agent-worker-actions.md)：目前的 worker 部署方式與待完成驗收，以此文件為準。
- [FastAPI Neon Agent 整合交接](2026-10-26-feng-agent-platform.md)：保留作為平台整合歷史紀錄；其中常駐 Render worker 部署方式已由 GitHub Actions 排程取代。
