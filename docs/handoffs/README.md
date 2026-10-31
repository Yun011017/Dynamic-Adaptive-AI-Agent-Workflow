# 交接文件規則

每次完成可由下一位接手的工作時，在此目錄新增一份文件，不修改或覆蓋既有交接內容。

檔名使用 `YYYY-MM-DD-負責範圍.md`，例如 `2026-10-26-feng-agent-platform.md`。

每份交接至少包含：完成內容、驗證方式、環境變數與憑證位置、已知限制、下一位可直接開始的工作，以及對應 commit。

## 最新狀態

- [2026-10-31 表單同步、Neon 入庫與 Agent 分析](2026-10-31-form-agent-neon.md)：本次唯一交接文件，包含所有改動、設定、操作、驗證、限制及接手工作。
- [2026-10-26 GitHub Actions Agent Worker 部署與驗收](2026-10-26-agent-worker-actions.md)：目前的 worker 部署方式與待完成驗收，以此文件為準。
- [FastAPI Neon Agent 整合交接](2026-10-26-feng-agent-platform.md)：保留作為平台整合歷史紀錄；目前 worker 以 GitHub Actions 排程執行。
