# Dynamic Adaptive AI Agent Workflow

以社團多渠道行銷為驗證情境的自適應 AI Agent 工作流程原型。

## 目錄

```text
frontend/                      使用者介面，目前只有說明
backend/
  app/                         FastAPI、ORM、連線、基本 API
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

## 本機啟動（Windows CMD）

需要 Python 3.11 或 3.12。在專案根目錄執行：

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

首次建立或更新 schema，從專案根目錄執行：

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m scripts.manage seed
..\.venv\Scripts\python.exe -m scripts.manage check
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

開啟 [API 文件](http://localhost:8000/docs) 與 [健康檢查](http://localhost:8000/health)。在 `/docs` 的 **Authorize** 填入開發金鑰後才能操作業務 API。按 `Ctrl+C` 停止後端。後續啟動只需從 `backend` 執行最後一行。

啟動 API 不會自動建表，也不會執行 seed；必須先跑 migration。`seed` 只建立虛構資料，不會發文或執行 Agent。

### 升級舊的三張表

只有原始 `goals`、`strategies`、`executions`，且從未使用 Alembic 的資料庫，先執行一次：

```bat
..\.venv\Scripts\python.exe -m scripts.manage baseline-legacy
..\.venv\Scripts\python.exe -m scripts.manage migrate
```

此專案目前設定的 Neon 已完成這個步驟，勿再執行 baseline。原型資料保留並歸到 `legacy` workspace；新 seed 放在 `development`。若既有 schema 不符，baseline 會拒絕，不可直接強制 stamp。

## 基本 API

| API | 功能 |
| --- | --- |
| `GET /health` | 真實檢查 DB；成功 200，DB 錯誤 503 |
| `POST /goals`、`GET /goals`、`GET /goals/{id}` | 建立／查詢目標 |
| `POST /goals/{id}/strategies` | 建立獨立策略版本；重複版本 409 |
| `POST /strategies/{id}/executions` | 建立 QUEUED 執行紀錄，不排程 Agent 或發文 |
| `GET /executions/{id}` | 查詢執行紀錄 |

業務 API 需 `Authorization: Bearer <PLATFORM_API_KEY>`。這是平台整合階段的單一 workspace 存取閘門，尚非完整 OIDC 登入／Admin、Agent RBAC／Audit。不得把此金鑰放入前端。完整登入與審核由架構安全模組接手，整合前不要將本 API 作為正式多人系統使用。

## 測試（CMD，從 backend 執行）

```bat
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

測試使用設定的 Neon direct 連線，建立隨機 `platform_test_*` schema，只在該 schema migration、seed 與寫入；結束只清除測試 schema。不要改成正式資料庫憑證。測試涵蓋 migration 與模型一致性、API 完整鏈、認證、跨工作空間 FK、事件／指標去重、seed 重跑、錯誤遮罩及讀取重試。

## 部署與協作

詳見 [後端部署與資料庫流程](backend/README.md) 與 [平台與資料庫驗收紀錄](docs/平台與資料庫驗收紀錄.md)。

GitHub CI 使用一次性 PostgreSQL service 測試，不需在你的電腦安裝 Docker。Development 自動部署需 repo 管理者配置 Secrets 與 Vercel Project 後啟用；目前本機檔案準備不代表雲端部署已完成。

完整系統設計見 [系統架構規格書](docs/系統架構規格書.md)。
