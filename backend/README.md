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

## 結構化表單回覆欄位

Migration `0005` 新增 `form_responses`，原始答案仍保存在 external_events，兩者以同 workspace 的 external_event_id 關聯：

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| is_member | nullable boolean | 是否為社員；是／否／未知 NULL 分開。 |
| will_attend | nullable boolean | 是否參加；缺少題目或未知答案不推定為否。 |
| event_date | nullable date | 活動日期，與填表時間分開。 |
| submitted_at | nullable timestamptz | 填表時間，統一 UTC。 |
| normalization_errors | JSON array | 無效答案／日期的欄位錯誤代碼，不包含原始答案。 |

另有 id、workspace_id、external_event_id、source_id、created_at。每個來源事件只能有一筆結構化回覆，跨 workspace 外鍵受 DB 約束。同步重跑會更新欄位對照結果，不新增重複回覆；既有事件在重新同步後補入新表。

題目名稱可在 backend/.env 設定，預設如下：

```dotenv
GOOGLE_FORMS_MEMBER_COLUMN=是否是社員
GOOGLE_FORMS_ATTENDANCE_COLUMN=是否要參加
GOOGLE_FORMS_EVENT_DATE_COLUMN=活動日期
GOOGLE_FORMS_SUBMITTED_AT_COLUMN=時間戳記
GOOGLE_FORMS_DATE_UTC_OFFSET_HOURS=8
```

「是／否」、社員與參加的明確文字選項及布林值會轉成 boolean，不猜測數字代碼或「尚未決定」。未知值存 NULL 並記錄錯誤碼；缺少題目則存 NULL。日期接受 YYYY-MM-DD／YYYY/MM/DD；Apps Script 的含時區 ISO 日期轉為設定 UTC offset 的當地日期，預設台灣 +8，避免午夜被轉成前一天。填表時間必須含時區，無法解析則存 NULL 並留錯誤碼。

先 migration 再同步（在 backend 目錄）：

```powershell
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m app.form_worker
```

目前資料源仍是原本兩筆 test/temp；不會因新增欄位而捏造社員或參加答案。使用者提供的「工作坊3－物聯網專題」只作格式參考，沒有更換來源：題目是姓名、是否是社員；沒有參加題，日期在活動說明中且為兩場，不自動推成每筆回覆日期或參加意願。姓名仍只保存在 raw_payload.answers，沒有新增姓名欄或傳給 Agent。

Agent 現在改從 form_responses 讀取結構化統計，詳細說明如下。

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync tests.test_form_fields -v
```

## Agent 讀取已匯入表單

`get_form_summary()` 定義於 app/form_summary.py，由 app/agent_runner.py 匯入。現在直接讀取 form_responses 的結構化欄位，不選取 external_events.raw_payload；僅 join 外部事件的來源 metadata，確保符合 provider、來源 ID 與匯入版本。worker 傳入工作 workspace_id；直接本機呼叫使用 PLATFORM_WORKSPACE_SLUG 的 active workspace。

只提供聚合結果：

| 摘要欄位 | 說明 |
| --- | --- |
| storage_table | form_responses |
| response_count | 已同步結構化回覆總筆數 |
| membership | 社員 yes／非社員 no／未知 unknown 筆數 |
| attendance | 願意參加 yes／不參加 no／未知 unknown 筆數 |
| event_dates | 每個活動日期的回覆筆數（ISO 日期） |
| event_date_unknown_count | 缺少活動日期的筆數 |
| submission_period | 填表時間已知／未知筆數及最早／最晚 UTC 時間 |
| normalization_error_count | 含正規化錯誤的回覆筆數，不包含錯誤原文 |
| summary_id | 當次摘要 SHA-256 |

不傳姓名、Email、原始答案、逐筆紀錄或來源 URL。未知不視為否，參加意願不等於實際到場，也不能解釋為內容偏好。舊 GOOGLE_FORMS_AGENT_NUMERIC_FIELDS 設定已不再使用，test/temp 不再進入摘要。

先執行 scripts.manage migrate 至 0005，再執行 app.form_worker 更新結構化資料；Agent 不會自行讀 Apps Script，也不會在 form_responses 無資料時回退原始資料或假摘要。已存在的 raw events 需重新同步補齊結構化列。空來源正常回報 0；查詢錯誤使工作失敗。

在 backend 目錄直接唯讀測試 local Agent，不建立工作紀錄也不呼叫外部模型：

```powershell
..\.venv\Scripts\python.exe -c "import json; from app.agent_runner import run_agent; print(json.dumps(run_agent(goal='分析表單社員與參加意願', context='', constraints={}), ensure_ascii=False, indent=2))"
```

前端建立新工作也使用相同摘要，重啟 API 與 Agent worker 即可。API data_source 仍為 neon_form_summary，前端不用更改；已完成工作保留舊結果，不回寫。輸出保存 form_summary／summary_id，local evidence 也保存社員、參加與日期依據。模型模式確認摘要工具被呼叫，但自然語言數字仍未逐一核對。

離線測試（不連 Neon）：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync tests.test_form_fields -v
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
