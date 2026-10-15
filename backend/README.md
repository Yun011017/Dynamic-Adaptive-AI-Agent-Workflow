# 後端、資料庫與部署流程

## 現況

FastAPI 使用 SQLAlchemy／psycopg 連接 Neon。Alembic 管理 schema；HTTP 啟動不再執行 DDL。八張核心表已在目前設定的 Neon 套用 migration，並有虛構 seed。

`PLATFORM_API_KEY` 僅是 development 單一 workspace API 閘門。完整 OIDC、Agent 服務身分、審核、Audit 及外部工具執行不在本次平台功能內；資料表的 members 不會自動把金鑰轉為正式登入帳號。

## Migration

- `0001`：原始三表基線，供空資料庫重建與既有原型採納。
- `0002`：八表、BIGINT 主鍵、UTC 時間、workspace 隔離、狀態限制、事件／策略版本唯一性。
- 既有原型資料歸入 `legacy`，不刪表重建；舊 timestamp 視為 UTC。
- Migration 以獨立 direct URL 與 PostgreSQL advisory lock 防止並行 DDL。
- `0002` 為 forward-only：禁止未審查的破壞性 downgrade；正式上線前須有經驗證的備份及復原方案。

新增欄位或表時，從 backend 的 CMD 執行：

```bat
..\.venv\Scripts\python.exe -m alembic revision --autogenerate -m add_feature
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

必須審查產生的 migration，尤其是 NOT NULL 回填、唯一鍵、刪除欄位與跨 workspace FK。已套用版本不得原地修改；先擴充相容 schema，再部署程式，最後另版清理。Migration 身分與 runtime 身分應分開授權；目前 `.env` 的角色權限尚需 Neon 管理者按環境配置，不能宣稱已完成最小權限。

## 核心資料表

| 表 | 約束 |
| --- | --- |
| workspaces | slug 唯一 |
| members | workspace + subject 唯一；role 只允許 Admin／Agent |
| goals | 所屬 workspace FK |
| strategies | 同 workspace Goal FK；goal + version 唯一，版本正整數 |
| executions | 同 workspace Strategy FK；狀態白名單 |
| execution_actions | 同 workspace Execution FK；action idempotency key 唯一；不提供外部執行 API |
| external_events | workspace + provider + account + source object + source version 唯一 |
| observations | 同 workspace 來源／策略／執行 FK；event + metric + observed_at 唯一 |

`source_account` 第一階段代表外部授權帳號／表單來源；後續 OAuth 模組加入 connection FK。保留 raw_payload 僅供受限匯入程式使用，基本 API 不開放原始個資查詢。Observation 必須同時使用一致的來源時間與來源版本，不能用每次匯入當下時間規避去重。

## 錯誤、重試與 connection pool

- API DB 例外統一遮罩：IntegrityError → 409，其餘 DB 例外 → 503；回應包含 request ID，不回傳 driver 原文、SQL 參數或連線資訊。
- session 隨每個 request 結束關閉，未完成交易回滾；寫入失敗不自動重試，避免重複副作用。
- `app/retry.py` 只提供可安全重做的讀取操作重試：初次失敗後最多 3 次，2／4／8 秒加 jitter；只重試連線／暫時不可用錯誤。發布、審核消耗、付款不得使用此 helper。
- `/health` 不在 HTTP request 內多次重試，連線 timeout 預設 10 秒，交由監控／呼叫端稍後重試。
- Vercel API 預設 NullPool＋Neon pooled URL，避免每個 function instance 保留連線。
- 長駐程式 `DB_POOL_MODE=queue` 使用 pool_size=2、max_overflow=0、pool_timeout=10；`pool_pre_ping` 檢查連線，connect timeout 可設定 1–30 秒。
- 不在資料庫交易內等人工審核或長時間外部 API。

## Vercel development Project

本專案是同一 Git repo 的 `backend` 子目錄。建立 Vercel Project 時：

1. 匯入有權存取的 GitHub repo，Root Directory 設為 `backend`，Framework 選 FastAPI。
2. 在該 development Project 的 Production environment 設定 `DATABASE_URL`（development database pooled URL）、`PLATFORM_API_KEY`、`PLATFORM_WORKSPACE_SLUG=development`、`DB_POOL_MODE=null`。
3. 不把 `.env` 上傳；`MIGRATION_DATABASE_URL` 僅放 GitHub development environment Secret，runtime 不需要它。
4. 首次雲端部署前先確認 migration 已套用。開啟部署網址 `/health` 應顯示 connected，再到 `/docs` 測試授權 API。

此處 Vercel 的 `--prod` 指 development Project 的固定部署網址，**不是正式業務 database**。日後 production 需另一組 Project／Secrets／database。

Vercel `git.deploymentEnabled=false` 刻意關閉內建每次 push 自動部署，避免測試或 migration 尚未完成就先上線。由下述 GitHub Actions 控制部署順序；首次匯入可能先產生一次部署，需先把環境變數與 DB migration 準備完成。

### GitHub Actions 配置

需要有 repository 管理設定權限的人，在 GitHub 建立 `development` environment，設定：

| Secret | 用途 |
| --- | --- |
| `NEON_DEV_MIGRATION_DATABASE_URL` | development Neon direct URL；CI migration 用 |
| `VERCEL_TOKEN` | 部署用 Vercel token；依團隊政策管理與撤銷 |
| `VERCEL_ORG_ID` | 你的 Vercel scope／team ID |
| `VERCEL_PROJECT_ID` | backend development Project ID |

再設定 repository variable `ENABLE_VERCEL_DEPLOY=true`。未啟用時，workflow 只跑 CI，雲端不被修改。

流程：PR／main → PostgreSQL 隔離測試 → main 的 development job → 檢查 Secrets → Neon migration → 固定版本 Vercel CLI pull／build／deploy → `/health` smoke check。部署 job 串行，migration 失敗就不部署；不在 deployment 自動執行 seed。若 Vercel Deployment Protection 要求登入，健康檢查需由管理者設定專用的自動化通道，不能直接關掉保護來取得測試成功。

CLI 從 repository 根目錄執行，由已連結 Project 的 Root Directory 決定建置 backend；不可把同一專案同時連結到不同 root。`.vercel/` 會保存拉取的設定與 secret，已加入 Git ignore。

此工作流程準備完成不代表 GitHub Secrets、GitHub App 授權或 Vercel Project 已在帳號中建立。Repo 不是你建立的仍可能部署，但要看 GitHub App 存取、repo 類型與 Vercel 方案；私人 repo 的 Hobby 協作有限制，請由有權限的擁有者設定或採符合團隊需求的方案，不修改 commit 身分來規避。

官方依據：[FastAPI](https://vercel.com/docs/frameworks/backend/fastapi)、[GitHub Actions](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel)、[Git 部署設定](https://vercel.com/docs/project-configuration/git-configuration)、[協作限制](https://vercel.com/docs/deployments/troubleshoot-project-collaboration)。

完整本機 CMD 指令與 seed／驗證方式見 [根目錄 README](../README.md)。
