# 後端

此目錄包含 FastAPI API、Neon migration 與 Agent worker 程式。後端負責驗證請求、存取 Neon、建立 Agent 工作與回傳執行結果；前端不會直接連資料庫。

## 表單同步 Worker

### 正式社團表單與人工／ai 歸因

#### 在介面新增多活動表單

Migration `0014` 新增 `form_sources`。在「內容提案」選擇策略後，於「報名表單綁定 → 新增表單」填寫名稱、Apps Script `/exec` 部署網址及試算表時區（預設 `Asia/Taipei`）。表單會自動歸屬目前策略的 Goal，即使尚無 Execution 也可先新增。新增不會呼叫 Google；儲存後按「同步回覆」讀取並匯入，再選擇人工／AI 來源綁定 Execution。Google 表單填寫網址、Sheets 編輯網址不是資料端點，不能直接填入。

API：`GET/POST /form-source-configs` 列出／建立來源；`PATCH /form-source-configs/{id}` 接收 `{"enabled":false}` 以停用同步；`POST /form-source-configs/{id}/sync` 同步單一來源並回傳 read/inserted/skipped。清單與新增結果不回傳 Apps Script 網址（可能含存取金鑰），也不回傳個資。來源名稱、活動與時區以外的來源識別會自動產生；同一工作區的同一網址不可重複新增。來源的活動與網址建立後固定，避免歷史回覆被錯置。

多個來源可以同時存在，Agent worker 只同步該次工作 Goal 的啟用來源；摘要及資料依據也只讀該活動的來源與觀測。每個來源各自一個交易，單一來源失敗不會刪除已保存回覆，先前成功來源不會回滾；worker 回報同步失敗並讀已保存資料。停用只停止同步，保留歷史資料與綁定，活動分析仍可讀取已保存回覆。正式欄位名稱沿用目前全域欄位對照，端點支援人工／ai 分組物件或含「文案來源」的二維陣列；每個來源可設定自己的時區。

工作區尚無資料庫來源時，保留 `.env` 的單來源相容模式。登記來源後改以資料庫為準，未登記的舊來源不會混入活動分析。若新增的網址等於既有 `.env` 網址，會沿用原 source_id 以保留回覆與去重身份；已有其他活動綁定時拒絕轉移。舊表單可在其正確活動下登記原網址後繼續使用，不必重新匯入為新來源。

Migration `0013` 新增 `form_execution_bindings`。在前端「內容提案」選擇策略後，可於「報名表單綁定」選擇 Execution 與已同步的表單來源（來源 ID＋人工／AI）並儲存。不需修改 `GOOGLE_FORMS_EXECUTION_MAP`；資料庫綁定優先於舊環境變數，同步時自動沿用。沒有 Execution 時先建立內容提案。綁定會在同一交易補齊該來源既有未關聯回覆，重複儲存不重複新增；來源或既有回覆已歸屬其他 Execution 時回傳 409，不支援重新歸因。匯入與綁定共用 workspace row lock，避免同步期間漏補回覆。

API：`GET /form-sources` 僅列來源、組別、筆數與綁定 Execution，不回傳姓名或 Email；`GET /strategies/{strategy_id}/executions` 列出策略下的執行紀錄；`POST /executions/{execution_id}/form-bindings` 接收 `{"source_id":"club-copy-ab-2026-11","copy_source":"人工"}`。所有端點沿用 API key 與 workspace 限制。來源可在第一筆回覆前綁定目前已設定端點的人工／ai 組別。

綁定本身不新增 KPI Observation；多活動網址由上述 `form_sources` 管理。來源使用後應保持固定，新的宣傳輪次請使用獨立來源。

支援原有的二維陣列，以及 Apps Script 回傳的物件：

```json
{"success":true,"data":{"人工":[{"時間戳記":"2026-11-21T10:30:00+08:00","電子郵件地址":"member@example.test","姓名":"測試社員","是否是社員":"是"}],"ai":[]}}
```

每組內容必須是答案物件的陣列；來源由群組名稱補入 `文案來源`，僅接受 `人工`／`ai`。兩組相同答案仍各保留一筆；重跑及欄位／群組排序不會新增重複資料。空表單應回傳空陣列。來源衝突、未知群組或非純量答案會拒絕整批，不將 API 錯誤當成零筆回覆。

Migration `0012` 在 `form_responses` 新增 `email`、`respondent_name`、`copy_source`、`execution_id`。前三者分別對照「電子郵件地址」「姓名」「文案來源」；社員對照「是否是社員」，選項是／否，其餘未知值保留 NULL。依報名規則，缺少參加意願題目或答案空白時預設為參加（true）；明確否定仍為 false，無法識別的非空答案仍為 NULL。原始答案仍保存在 `external_events.raw_payload.answers`；姓名與 Email 不加入既有 Agent 摘要。

在 `backend/.env` 設定本次實驗使用的 Execution ID（以下為示意，必須替換）：

```dotenv
GOOGLE_FORMS_SOURCE_ID=club-ab-2026-11
GOOGLE_FORMS_EXECUTION_MAP={"人工":101,"ai":102}
GOOGLE_FORMS_EMAIL_COLUMN=電子郵件地址
GOOGLE_FORMS_NAME_COLUMN=姓名
GOOGLE_FORMS_SOURCE_COLUMN=文案來源
```

Execution 必須存在且屬於同一工作區，資料庫另以複合外鍵保護。未設定對照的來源仍會匯入，但 `execution_id=NULL`；稍後設定再同步可補齊。已建立的關聯不能用不同設定重新歸因，移除設定也不會清除關聯。每次實驗使用不同且固定的來源 ID 與表單資料來源，避免將歷史回覆歸給新 Execution。此關聯代表表單來源對照，不證明個別填表者確實看過貼文；尚未自動建立 KPI Observation。

填表時間接受含時區的 ISO 8601（建議 Apps Script 用 `Date.toISOString()`）。若來源使用台灣時間且回傳無時區的 ISO、`YYYY/MM/DD HH:mm:ss` 或 `YYYY/MM/DD 上午/下午 h:mm:ss`，設定 `GOOGLE_FORMS_NAIVE_TIMEZONE=Asia/Taipei`；否則缺時區／無效時間保留 NULL 並記錄錯誤。中文時間明確處理上午／下午 12 點邊界，儲存時統一轉 UTC。

先在 backend 目錄執行 `..\.venv\Scripts\python.exe -m scripts.manage migrate`，設定網址與對照後再執行 `..\.venv\Scripts\python.exe -m app.form_worker`，並重啟 Agent worker。舊資料可透過原來源重跑補欄位；來源中新增欄位會改變內容雜湊，須避免將同一批舊資料以不同欄位集合重複匯入。

離線契約測試：`..\.venv\Scripts\python.exe -m unittest tests.test_registration_import tests.test_form_fields tests.test_form_sync -v`。PostgreSQL 的 `tests.test_platform.PlatformTests.test_official_registration_execution_attribution` 在隨機隔離 schema 驗證實際寫入、重跑、兩組 Execution 歸因及跨工作區外鍵，不讀取真實表單回覆。

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

此指令可獨立同步一次後結束，不呼叫模型。`app.agent_worker` 現在每領取一筆工作也會先嘗試同步，平常不必另外手動執行本指令。輸出 `read`、`inserted`、`skipped` 筆數；失敗回傳非零 exit code，不印原始資料或憑證。

逐筆答案保存於 Neon `external_events.raw_payload.answers`，擷取時間為 `raw_payload.fetched_at`，provider 為 `google_forms_apps_script`，source_account 為上述來源 ID。來源時間欄位原樣保存在 answers，不另猜測題目語意。所有回覆先驗證，再於單一交易寫入，失敗整批回滾。

使用整列欄名與答案的穩定 SHA-256 作為 source_object_id，source_version 固定為 `content-sha256-v1`，透過既有 `uq_external_event_source` 與 PostgreSQL ON CONFLICT 避免重跑／併發重複寫入。列順序和欄順序改變不影響識別，擷取時間不參與雜湊。完全相同的兩份回覆會合併；修改內容視為新資料，刪除來源回覆不會刪除已匯入資料。此版本不提供穩定 response ID 或回覆修改歷史。

若來源含個資，answers 也會保存；本階段僅用使用者提供的無個資連線測試表，不提供原始內容前端 API，也不傳給 Agent。正式資料需先設計欄位白名單與來源授權。

離線測試：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_form_sync -v
```

`tests.test_platform` 另含真實 PostgreSQL 的兩次匯入去重測試，僅在隔離測試資料庫執行。

## 結構化表單回覆欄位

Migration `0005` 建立 `form_responses`；`0006` 新增學校、系級及活動名稱。原始答案仍保存在 external_events，兩者以同 workspace 的 external_event_id 關聯：

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| is_member | nullable boolean | 是否為社員；是／否／未知 NULL 分開。 |
| will_attend | nullable boolean | 是否參加；缺少題目或空白預設 true，明確否定 false，未知非空答案 NULL。 |
| school | nullable varchar(255) | 學校，供客群統計。 |
| department_grade | nullable varchar(255) | 系級，保留合併文字，不猜測科系與年級。 |
| activity_name | nullable varchar(255) | 參加的活動名稱，取代原活動日期用途。 |
| submitted_at | nullable timestamptz | 填表時間，統一 UTC。 |
| normalization_errors | JSON array | 無效答案／日期的欄位錯誤代碼，不包含原始答案。 |

另有 id、workspace_id、external_event_id、source_id、created_at。每個來源事件只能有一筆結構化回覆，跨 workspace 外鍵受 DB 約束。同步重跑會更新欄位對照結果，不新增重複回覆；既有事件在重新同步後補入新表。

題目名稱可在 backend/.env 設定，預設如下：

```dotenv
GOOGLE_FORMS_MEMBER_COLUMN=是否是社員
GOOGLE_FORMS_ATTENDANCE_COLUMN=是否要參加
GOOGLE_FORMS_SCHOOL_COLUMN=學校
GOOGLE_FORMS_DEPARTMENT_GRADE_COLUMN=系級
GOOGLE_FORMS_ACTIVITY_COLUMN=參加的活動
GOOGLE_FORMS_SUBMITTED_AT_COLUMN=時間戳記
```

「是／否」、社員與參加的明確文字選項及布林值會轉成 boolean，不猜測數字代碼或「尚未決定」。未知值存 NULL 並記錄錯誤碼；缺少社員題目仍存 NULL，缺少參加意願題目或空白答案預設 true。學校、系級、活動名稱須為文字，經 NFKC、頭尾去空白與連續空白合併，最多 255 字元；缺漏存 NULL，無效型別或過長資料記錄錯誤碼。不自行合併學校簡稱，也不拆分系級。活動目前為單一文字，複選整格內容不會自動拆成多場活動。填表時間必須含時區，內部仍轉 UTC。舊 event_date 僅保留歷史資料，不再匯入或供 Agent 查詢，日期不會被轉成活動名稱；舊日期設定已不再使用。

先 migration 再同步（在 backend 目錄）：

```powershell
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m app.form_worker
```

目前資料源仍是原本兩筆 test/temp；不會因新增欄位而捏造社員或參加答案。使用者提供的「工作坊3－物聯網專題」只作格式參考，沒有更換來源：題目是姓名、是否是社員；沒有參加題，依目前規則參加意願預設 true；日期在活動說明中且為兩場，不自動推成每筆回覆日期。姓名仍只保存在 raw_payload.answers，沒有新增姓名欄或傳給 Agent。

Agent 現在改從 form_responses 讀取結構化統計，詳細說明如下。

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync tests.test_form_fields tests.test_agent_worker -v
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
| schools／school_unknown_count | 各學校筆數及缺漏筆數 |
| department_grades／department_grade_unknown_count | 各系級筆數及缺漏筆數 |
| activities／activity_unknown_count | 各參加活動名稱筆數及缺漏筆數 |
| submission_period | 填表時間已知／未知筆數及最早／最晚 UTC 時間 |
| normalization_error_count | 含正規化錯誤的回覆筆數，不包含錯誤原文 |
| summary_id | 當次摘要 SHA-256 |

不傳姓名、Email、原始答案、逐筆紀錄或來源 URL。未知不視為否，參加意願不等於實際到場，也不能解釋為內容偏好。舊 GOOGLE_FORMS_AGENT_NUMERIC_FIELDS 設定已不再使用，test/temp 不再進入摘要。

先執行 scripts.manage migrate 至 0006。Agent worker 領取工作後會先同步 Apps Script，再讀 form_responses；同步失敗會回滾同步交易，沿用已保存資料。單獨呼叫 run_agent／get_form_summary 不會同步，也不會在 form_responses 無資料時回退原始資料或假摘要。已存在的 raw events 需重新同步補齊結構化列。空來源正常回報 0；查詢錯誤使工作失敗。

在 backend 目錄直接唯讀測試 local Agent，不建立工作紀錄也不呼叫外部模型：

```powershell
..\.venv\Scripts\python.exe -c "import json; from app.agent_runner import run_agent; print(json.dumps(run_agent(goal='分析表單社員與參加意願', context='', constraints={}), ensure_ascii=False, indent=2))"
```

前端建立新工作也使用相同摘要，重啟 API 與 Agent worker 即可。API data_source 仍為 neon_form_summary，前端不用更改；已完成工作保留舊結果，不回寫。輸出保存 form_summary／summary_id，local evidence 也保存社員、參加、學校、系級與活動依據。模型模式確認摘要工具被呼叫，但自然語言數字仍未逐一核對。

離線測試（不連 Neon）：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync tests.test_form_fields tests.test_agent_worker -v
```

## Agent worker 自動同步與失敗回退

每筆工作流程為「領取並提交 RUNNING → 獨立交易同步表單 → 從 form_responses 讀摘要 → Agent 分析 → 保存結果」。沒有等待工作的閒置輪詢不會讀取表單，避免每兩秒重複連線；若只想同步而不分析，仍可執行 app.form_worker。

同步失敗（網址未設定、連線、格式或寫入錯誤）不會直接讓 Agent 工作失敗，改讀資料庫舊資料。沒有舊回覆時回報資料不足，不補假資料；若 Neon 本身無法讀取或 Agent 執行失敗，工作仍為 FAILED。既有外部來源只綁定 PLATFORM_WORKSPACE_SLUG，其他 workspace 的工作不能將這個來源匯入其範圍。

結果新增 output_payload.form_sync：status、attempted_at、成功時 read／inserted／skipped、失敗時遮罩 error_code／message，以及 fallback_used。只有同步失敗且摘要確實有舊資料時 fallback_used=true。前端現有「建議依據」會顯示失敗沿用舊資料或無資料的提示，無需改前端。結束 checkpoint 也保存同步狀態，不保存例外原文。

啟用只需重啟 Agent worker，建立新工作；已完成工作不會重算。GitHub Actions 新增 Secret GOOGLE_FORMS_APPS_SCRIPT_URL，以及可選 Variables GOOGLE_FORMS_SOURCE_ID、PLATFORM_WORKSPACE_SLUG 與各 GOOGLE_FORMS_*_COLUMN；範例預設同本機。未設定端點時允許回退，不阻擋原有 Agent 工作。此次僅修改 workflow，未更新 repository 設定或部署。

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
