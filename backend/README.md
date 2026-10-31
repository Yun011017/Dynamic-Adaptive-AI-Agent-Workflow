# 後端

此目錄包含 FastAPI API、Neon migration 與 Agent worker 程式。後端負責驗證請求、存取 Neon、建立 Agent 工作與回傳執行結果；前端不會直接連資料庫。

## 表單同步 Worker

在 `backend/.env` 設定（實際網址只放本機或部署環境，不提交 Git）：

```dotenv
GOOGLE_FORMS_APPS_SCRIPT_URL=你的AppsScript部署網址
GOOGLE_FORMS_SOURCE_ID=connection-test
```

沿用 `DATABASE_URL` 與 `PLATFORM_WORKSPACE_SLUG`。來源 ID 是這張表單固定的內部名稱；換另一張表單需使用不同 ID，單純重跑不要更改。只接受 Google HTTPS `/macros/s/.../exec` 部署，現有 Apps Script 二維陣列無須修改。

在 backend 目錄執行一次同步：

```powershell
..\.venv\Scripts\python.exe -m app.form_worker
```

此指令讀取一次後結束，獨立於 `app.agent_worker`，不呼叫模型、沒有前端觸發或自動排程。輸出 `read`、`inserted`、`skipped` 筆數；失敗回傳非零 exit code，不印原始資料或憑證。

逐筆答案保存於 Neon `external_events.raw_payload.answers`，擷取時間為 `raw_payload.fetched_at`，provider 為 `google_forms_apps_script`，source_account 為上述來源 ID。來源時間欄位原樣保存在 answers，不另猜測題目語意。所有回覆先驗證，再於單一交易寫入，失敗整批回滾。

使用整列欄名與答案的穩定 SHA-256 作為 source_object_id，source_version 固定為 `content-sha256-v1`，透過既有 `uq_external_event_source` 與 PostgreSQL ON CONFLICT 避免重跑／併發重複寫入。列順序和欄順序改變不影響識別，擷取時間不參與雜湊。完全相同的兩份回覆會合併；修改內容視為新資料，刪除來源回覆不會刪除已匯入資料。此版本不提供穩定 response ID 或回覆修改歷史。

若來源含個資，answers 也會保存；本階段僅用使用者提供的無個資連線測試表，不提供原始內容前端 API，也不傳給 Agent。正式資料需先設計欄位白名單與來源授權。

離線測試：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_form_sync -v
```

`tests.test_platform` 另含真實 PostgreSQL 的兩次匯入去重測試，僅在隔離測試資料庫執行。

## Agent 讀取已匯入表單

`app.agent_runner.get_form_summary()` 現在從 Neon `external_events` 查詢，沒有固定 30 人的假摘要，也不會在查詢失敗時回退成假資料。worker 傳入工作所屬 workspace_id，查詢再限制 provider、GOOGLE_FORMS_SOURCE_ID、form_response 與匯入版本。直接本機呼叫時使用 PLATFORM_WORKSPACE_SLUG 對應的 active workspace。

新增可選設定：

```dotenv
GOOGLE_FORMS_AGENT_NUMERIC_FIELDS=test,temp
```

僅這份逗號分隔白名單的數值欄位會提供 count、missing_or_invalid、min、max、mean；不把布林、數字字串或非有限數值強制轉成數字。回覆總數不因欄位缺值而減少。Agent 不會收到逐筆答案、來源網址、Email、時間戳或其他未列入白名單的欄位。空白白名單代表只提供回覆總數。

先執行表單同步，再執行 Agent；Agent 只讀資料庫，不直接重新抓 Apps Script。需要更新資料時重新執行 form_worker。以本機 local 模式唯讀測試，不寫入工作歷史也不呼叫模型：

```powershell
..\.venv\Scripts\python.exe -c "import json; from app.agent_runner import run_agent; print(json.dumps(run_agent(goal='分析已匯入表單', context='', constraints={}), ensure_ascii=False, indent=2))"
```

前端建立新工作也會使用相同 Neon 摘要；請重啟 API 與 agent_worker。新工作 data_source 預設且僅接受 neon_form_summary，前端省略此欄即可。歷史完成工作仍保留原輸出；舊等待工作若保存了原 synthetic 標籤，新 worker 執行時仍改讀 Neon，不再使用假資料。

輸出保留 form_summary 與 summary_id（聚合內容 SHA-256）以追溯當次讀取的資料。local 模式直接根據統計回報結果，模型模式必須呼叫摘要工具；模型文字的數字正確性目前仍需額外驗證，不能由工具已呼叫推定整段文字完全正確。當前 test/temp 未定義業務意義，不將其解釋為活動偏好，亦不宣稱已有足夠資料推論受眾。

離線測試（不連 Neon）：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync -v
```

---

以下為維護 migration、資料表與部署時的技術備註。

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
- Vercel API 預設以 NullPool 搭配 Neon pooled URL，避免每個 function instance 保留連線。
- GitHub Actions worker 的連線與執行設定集中在 `.github/workflows/agent-worker.yml`，不放進本機或 Vercel 環境變數。
- 不在資料庫交易內等人工審核或長時間外部 API。
