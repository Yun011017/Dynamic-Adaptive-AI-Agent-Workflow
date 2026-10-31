# 2026-10-31 表單同步、Neon 入庫與 Agent 分析交接

本文件合併本次表單同步與 Agent 摘要讀取的所有變更，是本次工作唯一交接文件。基於重設後的 dengdee／main 實作；先前捨棄的表單功能不在本次交付範圍。

## 1. 完成範圍與資料流

```text
Google Forms → 連動 Sheets → 既有 Apps Script doGet
  → app.form_worker（手動執行一次）
  → 格式驗證、內容雜湊、單一交易寫入 Neon external_events
  → app.agent_worker 領取 Agent 工作，傳入工作所屬 workspace_id
  → get_form_summary() 從 Neon form_responses 讀取限定來源的結構化統計
  → local 規則／模型工具流程產生結果
  → agent_runs.output_payload 保存建議及摘要快照
  → 前端透過原有 API 查詢工作結果
```

已完成：讀取目前測試表單、寫入資料庫、重跑去重、取代寫死的 30 人假摘要、工作空間與來源篩選、社員／參加意願／日期統計、結果追溯及離線測試。

新增 migration 0005 與 form_responses 結構化表單回覆表；沒有修改 Google 端 Apps Script、前端、依賴或部署設定。兩個 worker 分開執行：form_worker 更新資料；agent_worker 處理 Agent 工作。Agent 不會自動抓取 Apps Script，也不會自動啟動同步 worker。

## 2. 變更檔案

| 檔案 | 內容 |
| --- | --- |
| `backend/app/form_sync.py`（新增） | 讀取 Apps Script、Google URL／重新導向限制、20 秒 timeout、2 MB 上限、表格驗證、SHA-256 與 PostgreSQL 去重寫入。 |
| `backend/app/form_worker.py`（新增） | 一次性同步入口，僅輸出筆數，錯誤回傳非零 exit code 並遮罩敏感資訊。 |
| `backend/app/form_fields.py`（新增） | 將社員、參加與日期題目明確映射為結構化欄位，未知值保留 NULL 與錯誤代碼。 |
| `backend/app/models.py` | 新增 FormResponse ORM，含跨 workspace 外鍵與事件唯一鍵。 |
| `backend/migrations/versions/0005_form_responses.py`（新增） | 非破壞性新增 form_responses 表，已套用 Neon。 |
| `backend/scripts/manage.py` | check 納入新資料表。 |
| `backend/tests/test_form_fields.py`（新增） | 布林、缺值、映射、日期與時區測試。 |
| `backend/app/form_summary.py`（新增） | get_form_summary() 的定義位置，查詢 Neon，輸出允許欄位的聚合摘要與雜湊。 |
| `backend/app/agent_runner.py` | 匯入共用摘要工具，取代固定假資料；local 依真實統計回報，模型透過 get_form_summary_tool() 取得摘要，保存 form_summary／summary_id。 |
| `backend/app/agent_worker.py` | 將 row.workspace_id 傳給 run_agent，讓摘要使用工作所屬範圍。 |
| `backend/app/config.py` | 新增表單端點、來源 ID、題目對照與日期時區設定；最終移除舊數值白名單設定。 |
| `backend/app/schemas.py` | AgentRunCreate.data_source 預設且只接受 neon_form_summary。 |
| `backend/.env.example` | 新增上述環境變數範本，不含實際網址或憑證。 |
| `backend/tests/test_form_sync.py`（新增） | 同步資料驗證、雜湊穩定性、URL／來源 ID 與網路錯誤測試。 |
| `backend/tests/test_agent_runner.py` | Neon 摘要使用、資料改變、空資料、失敗不回退、欄位排除、模型工具資料傳遞與 API 來源測試。 |
| `backend/tests/test_platform.py` | 更新來源斷言，新增 PostgreSQL 匯入去重、來源／workspace 隔離及 Agent 使用摘要的整合測試；尚未執行本套件。 |
| `backend/README.md` | 本機設定、同步與 Agent 操作、資料儲存及限制。 |
| `docs/handoffs/README.md` | 更新本次唯一交接入口。 |
| `docs/handoffs/2026-10-31-form-agent-neon.md`（新增） | 本文件；取代本次兩份階段交接文件。 |

`agent_lab/` 未修改，仍為獨立歷史原型。網站目前使用 backend 的 Agent 實作。

## 3. 環境設定與表單選擇

設定放 `backend/.env`，不提交實際憑證：

```dotenv
DATABASE_URL=你的Neon連線
PLATFORM_WORKSPACE_SLUG=development
GOOGLE_FORMS_APPS_SCRIPT_URL=你的AppsScript部署網址
GOOGLE_FORMS_SOURCE_ID=connection-test
AGENT_PROVIDER=local
AGENT_MODEL=deterministic-langgraph
```

DATABASE_URL 與 PLATFORM_WORKSPACE_SLUG 沿用原有設定；前端／API 仍使用原本 PLATFORM_API_KEY 驗證。local 不需模型金鑰；Gemini、OpenAI、Claude 使用各自的後端憑證，未做此次真實模型驗收。

GOOGLE_FORMS_APPS_SCRIPT_URL 決定同步去哪裡讀取；GOOGLE_FORMS_SOURCE_ID 是固定表單識別，寫入 source_account，也用於 Agent 查詢。相同表單重跑不要改 ID，換表單需給不同 ID，避免混用資料。改設定後重啟 API 與 Agent worker，再建立新工作。

目前整個後端部署使用一組來源設定，前端不能針對每筆工作選表單。雲端 worker 不會讀本機 .env；若使用雲端，需另外設定同樣的來源 ID 與白名單。此次沒有變更 GitHub／Vercel 設定或部署。

## 4. Apps Script 與同步規則

沿用使用者既有 doGet，讀「表單回覆 1」並回傳二維 JSON，第一列為標題。無需修改腳本：

```json
[
  ["時間戳記", "test", "temp"],
  ["2026-10-31T02:00:00Z", 1, 4]
]
```

標題必須為不重複的非空白文字，每列欄數相同；只接受有限 JSON scalar 儲存格，全空列略過。只有標題代表零回覆；缺少標題、非 JSON、錯誤列寬等會失敗，不偽裝為零回覆。來源時間欄位原樣保留，沒有猜測其語意。

URL 限 Google HTTPS `/macros/s/.../exec`，重新導向僅 script.google.com／script.googleusercontent.com，連線 timeout 20 秒，回應上限 2 MB。不記錄原始答案或憑證。外部資料先完整驗證，再開資料庫交易，批次寫入失敗時整批回滾。

儲存位置與欄位：

| external_events 欄位 | 值／用途 |
| --- | --- |
| workspace_id | 設定的 active workspace |
| provider | google_forms_apps_script |
| source_account | GOOGLE_FORMS_SOURCE_ID |
| source_object_id | 整列欄名與值 canonical JSON 的 SHA-256 |
| source_version | content-sha256-v1 |
| event_type | form_response |
| processing_status | RECEIVED |
| raw_payload.answers | 原始欄名與答案 |
| raw_payload.fetched_at | UTC 匯入時間 |

使用既有 uq_external_event_source 唯一鍵與 ON CONFLICT DO NOTHING，防止重跑／併發重複。雜湊排除列順序、欄順序與擷取時間，內容不變即相同身份。

限制：完全相同的兩份回覆會合併；修改答案視為新資料，不識別原回覆更新；來源刪除不刪除已匯入事件。因此 response_count 是累積匯入事件數，不能保證是真實人數或來源目前有效回覆數。正式版本需要穩定 response_id 與版本處理。

## 5. Agent 查詢、白名單與結果

get_form_summary() 定義於 app/form_summary.py，app/agent_runner.py 匯入；模型用的 get_form_summary_tool() 包裝位於 agent_runner.py。最新版本從 form_responses 選取 is_member、will_attend、event_date、submitted_at、normalization_errors，不讀 raw_payload；僅 join external_events 以限制來源 metadata。

查詢同時限制 active workspace、google_forms_apps_script provider、設定來源 ID、form_response 類型與 content-sha256-v1 版本。worker 以工作記錄傳 workspace_id；本機直接呼叫使用 PLATFORM_WORKSPACE_SLUG。模型不能指定 workspace、URL、SQL 或任意欄位。

輸出白名單為 source=neon_form_summary、storage_table=form_responses、source_id、response_count、membership（yes/no/unknown）、attendance（yes/no/unknown）、event_dates（日期到筆數）、event_date_unknown_count、submission_period（已知／未知數及最早／最晚 UTC 時間）、normalization_error_count（有錯誤的回覆數）、notice、summary_id。不提供逐筆紀錄、姓名、Email、原始答案、錯誤原文或來源 URL。

local 結果會引用社員、參加與日期統計，有明確參加意願才建議行前資訊等後續；未知不當成否，意願不當成實際到場或內容偏好。模型同樣取得此摘要，但尚未做自然語言數字逐一驗證。兩條路徑保存摘要快照與 SHA-256；local 另附統計 evidence。

GOOGLE_FORMS_AGENT_NUMERIC_FIELDS 已移除，舊 .env 同名設定會被忽略，test/temp 不再被模型讀取。form_responses 無資料回報 0 並提示同步，不回退原始事件或假資料。不存在 workspace 或 DB 錯誤則直接失敗。API data_source 維持 neon_form_summary，前端不需改動；歷史完成工作不改寫。

## 6. 本機操作

以下同步與測試指令均在 backend 目錄執行，使用 Python 3.11 或 3.12 及專案依賴。

先同步一次（不需開前端、API 或模型）：

```powershell
..\.venv\Scripts\python.exe -m app.form_worker
```

此指令讀一次後結束，輸出 read／inserted／skipped。目前沒有自動輪詢、同步佇列、前端觸發或排程；來源更新後要重新執行。

直接唯讀測試 local Agent，不建立資料庫工作、不呼叫外部模型：

```powershell
..\.venv\Scripts\python.exe -c "import json; from app.agent_runner import run_agent; print(json.dumps(run_agent(goal='分析已匯入表單', context='', constraints={}), ensure_ascii=False, indent=2))"
```

若透過網站操作，分別啟動 API 與 worker：

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
..\.venv\Scripts\python.exe -m app.agent_worker
```

另在 frontend 目錄 `npm run dev`，設定 API URL／Development API key，再建立新工作。預期 PENDING → RUNNING → COMPLETED。停在 PENDING 時檢查 worker 是否啟動，以及 API／worker 是否連同一 Neon；已建立工作保存當時 provider/model，修改 provider 後請建立新工作。

## 7. 驗證結果

真實 Apps Script → Neon 已執行兩次：

| 執行 | read | inserted | skipped |
| --- | ---: | ---: | ---: |
| 第一次 | 2 | 2 | 0 |
| 第二次 | 2 | 0 | 2 |

實際新增 2 筆，第二次不重複。這是使用者授權的資料匯入，不是在正式 Neon 跑測試套件。

第一階段歷史驗證（目前已改讀結構化欄位）：真實 Neon → local Agent 唯讀驗證曾取得 2 筆；test 有效 2 筆、min=1、max=2、mean=1.5；temp 有效 2 筆、min=4、max=6、mean=5。該次僅讀資料庫，沒有讀 Apps Script、寫資料庫或呼叫付費模型。最新 form_responses 驗證見第 11 節。

最終離線測試：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync tests.test_form_fields -v
```

20 項通過，涵蓋內容雜湊、格式與空列、來源限制、網路錯誤遮罩、欄位白名單、無效數值、資料改變影響結果、空資料、DB 失敗不回退、模型工具傳遞、未知／否區分、日期彙整及 API 來源。另通過 compileall、git diff --check。

未執行：新增的 tests.test_platform PostgreSQL 整合套件、此次真實模型呼叫、前端到 worker 完整驗收、雲端部署驗收。資料庫整合測試僅在隔離 PostgreSQL 執行，不使用正式 Neon。

## 8. 限制與下一步

1. 先在隔離 PostgreSQL 執行 tests.test_platform，驗證真實 DB 去重與 workspace／來源隔離。
2. 定義正式題目與分析指標；目前只支援描述統計，沒有偏好分類、自由文字主題或統計推論。
3. 加入模型引用數字驗證，必要時前端呈現摘要快照。
4. 增加穩定 response_id、更新版本與來源刪除規則；目前雜湊方案只供第一階段驗證。
5. 再設計同步排程／持久化工作、同步紀錄、自動重試與多表單 connection 管理。

同步目前保存全部來源欄位，僅用無個資的連線測試資料；正式含個資表單需先定保存白名單與來源端存取權限。摘要層排除個資不能代替原始來源保護。尚無 OAuth、原始資料前端 API 或同步紀錄表。摘要查詢載入該範圍全部回覆，大資料量時需改成 DB 端聚合／分批處理。

## 9. 版本與交付

修改前 HEAD 為 c6570d4（Update Worker Deployment Documentation）。本文件與功能以同一筆「feat: 串接表單同步至 Neon 並讓 Agent 讀取真實摘要」提交至 dengdee；實際 commit hash 以 Git 紀錄為準。遠端原先被捨棄的表單版本以 force-with-lease 更新為本次重做版本，不修改 main。設定檔中的實際端點、DB URL 與模型／平台 key 不包含在本文件。


## 10. 結構化欄位補充（同日後續修改）

依使用者要求新增資料庫欄位記錄社員、參加與日期，與本次交接合併，不另建交接文件。

### 新增資料表

Neon 已套用 0005，新增 form_responses：id、workspace_id、external_event_id、source_id、is_member（nullable boolean）、will_attend（nullable boolean）、event_date（nullable date）、submitted_at（nullable timestamptz）、normalization_errors（JSON array）、created_at。同 workspace／external_event_id 唯一，複合外鍵指向 external_events 防止跨 workspace 關聯。原始答案保留，不刪除既有資料。

新增 app/form_fields.py，form_sync.save_responses() 在同一交易先寫／定位原始事件，再 upsert 結構化回覆；重跑可補齊舊事件的新欄位並更新對照，不會重複增加 form_responses。事件 inserted/skipped 輸出維持原意，skipped 不代表略過結構化更新。

### 欄位對照與日期

```dotenv
GOOGLE_FORMS_MEMBER_COLUMN=是否是社員
GOOGLE_FORMS_ATTENDANCE_COLUMN=是否要參加
GOOGLE_FORMS_EVENT_DATE_COLUMN=活動日期
GOOGLE_FORMS_SUBMITTED_AT_COLUMN=時間戳記
GOOGLE_FORMS_DATE_UTC_OFFSET_HOURS=8
```

欄位名需完全符合工作表標題。接受明確中文是／否、社員／非社員、參加／不參加與 yes/no/true/false，數字代碼及未知答案不推斷，存 NULL 並記錄欄位錯誤代碼。缺少題目則 NULL，不視為否。

活動日期與填表時間分開：活動日期接受 YYYY-MM-DD、YYYY/MM/DD 或含時區 ISO datetime，後者依 UTC offset 轉為當地日曆日期（預設台灣 +8）；填表時間須含時區，內部轉 UTC。日期不合法時保留 NULL 與診斷代碼。

使用者提供「工作坊3－物聯網專題」表單作格式參考，已唯讀檢視題目為「姓名」「是否是社員」（是／否）。沒有是否參加／日期題目，活動說明列兩場日期，不能推成單一活動日期，也不因填表就推定參加。使用者確認沒有對應 Apps Script、不是新資料源，因此沒有更換現有 URL 或 source ID。姓名仍在 raw_payload.answers，未新增姓名欄，亦不向 Agent 傳送。

### 操作與驗證

先執行 scripts.manage migrate，再執行 app.form_worker。Neon migration 已成功；既有兩筆測試回覆已重新同步（read=2、inserted=0、skipped=2），用於補入結構化表。test/temp 沒有社員、參加或活動日期答案，欄位須保持 NULL，來源時間戳正常解析。

19 項離線測試通過，另已審查 0005 的 SQL 輸出。tests.test_platform 新增結構化入庫、重跑去重與重新映射測試，migration 斷言更新為 0005；尚未在隔離 PostgreSQL 跑完整套件。此為結構化入庫階段的驗證；後續 Agent 已改用這些結構化欄位，見第 5、11 節。無需修改 Apps Script；改成正式題目後依上方設定對照再同步即可。


## 11. Agent 改用 form_responses（同日最終狀態）

依使用者要求，Agent 摘要入口現在只選取 form_responses 的結構化欄位。先前 test/temp 平均值驗證為歷史紀錄，不再是目前摘要內容。沒有新增 migration 或更換表單來源，前端與工作佇列 API 不變。

修改 app/form_summary.py、app/agent_runner.py、app/config.py、.env.example、tests/test_agent_runner.py、tests/test_platform.py、backend/README.md 及本交接。移除數值欄位設定、更新 local 建議／模型提示；整合測試改驗證結構化統計與來源／workspace 隔離。

20 項離線測試通過，確認結構化值改變會影響結果、未知不算成否、日期分組、模型工具資料傳遞、不洩漏個資、DB 失敗不回退及空資料處理。真實模型與隔離 PostgreSQL 完整套件尚未執行。重啟 API／Agent worker 後建立新工作即可使用最新流程，最新程式與本文件以「feat: 新增結構化表單欄位並讓 Agent 讀取 form_responses」共同提交至 dengdee，實際 hash 以 Git 紀錄為準。

真實 Neon 到 local Agent 的最新唯讀驗證成功：storage_table=form_responses、2 筆回覆；membership 與 attendance 均為 yes=0、no=0、unknown=2，活動日期沒有已知值，填表時間已知 2 筆，正規化錯誤 0 筆。沒有讀取 Apps Script、寫入資料庫或呼叫付費模型。這符合現有 test/temp 資料沒有社員／參加答案的情況，沒有捏造否定答案或回退原始數值。
