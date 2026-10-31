# 2026-10-31 表單同步、Neon 入庫與 Agent 分析交接

本文件合併本次表單同步與 Agent 摘要讀取的所有變更，是本次工作唯一交接文件。基於重設後的 dengdee／main 實作；先前捨棄的表單功能不在本次交付範圍。

## 1. 完成範圍與資料流

```text
Google Forms → 連動 Sheets → 既有 Apps Script doGet
  → app.form_worker（手動執行一次）
  → 格式驗證、內容雜湊、單一交易寫入 Neon external_events
  → app.agent_worker 領取 Agent 工作，傳入工作所屬 workspace_id
  → get_form_summary() 從 Neon 讀取限定來源的統計
  → local 規則／模型工具流程產生結果
  → agent_runs.output_payload 保存建議及摘要快照
  → 前端透過原有 API 查詢工作結果
```

已完成：讀取目前測試表單、寫入資料庫、重跑去重、取代寫死的 30 人假摘要、工作空間與來源篩選、數值白名單統計、結果追溯及離線測試。

沒有修改 Google 端 Apps Script、前端、資料表、migration、依賴或部署設定。兩個 worker 分開執行：form_worker 更新資料；agent_worker 處理 Agent 工作。Agent 不會自動抓取 Apps Script，也不會自動啟動同步 worker。

## 2. 變更檔案

| 檔案 | 內容 |
| --- | --- |
| `backend/app/form_sync.py`（新增） | 讀取 Apps Script、Google URL／重新導向限制、20 秒 timeout、2 MB 上限、表格驗證、SHA-256 與 PostgreSQL 去重寫入。 |
| `backend/app/form_worker.py`（新增） | 一次性同步入口，僅輸出筆數，錯誤回傳非零 exit code 並遮罩敏感資訊。 |
| `backend/app/form_summary.py`（新增） | get_form_summary() 的定義位置，查詢 Neon，輸出允許欄位的聚合摘要與雜湊。 |
| `backend/app/agent_runner.py` | 匯入共用摘要工具，取代固定假資料；local 依真實統計回報，模型透過 get_form_summary_tool() 取得摘要，保存 form_summary／summary_id。 |
| `backend/app/agent_worker.py` | 將 row.workspace_id 傳給 run_agent，讓摘要使用工作所屬範圍。 |
| `backend/app/config.py` | 新增表單端點、來源 ID、Agent 數值欄位設定。 |
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
GOOGLE_FORMS_AGENT_NUMERIC_FIELDS=test,temp
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

get_form_summary() 定義於 app/form_summary.py，app/agent_runner.py 匯入；模型用的 get_form_summary_tool() 包裝位於 agent_runner.py。

查詢必須同時符合：active workspace、google_forms_apps_script provider、設定來源 ID、form_response 類型與 content-sha256-v1 版本。worker 以工作記錄傳 workspace_id；直接本機呼叫未傳時，使用 PLATFORM_WORKSPACE_SLUG 查找。模型不能自行指定 workspace、URL、SQL 或欄位。

只彙整 GOOGLE_FORMS_AGENT_NUMERIC_FIELDS 的欄位，預設 test,temp；逗號分隔，設空白則僅回報筆數。統計為 count、missing_or_invalid、min、max、mean。布林、數字字串及非有限值不轉成有效數字；缺值不會減少總回覆數。

摘要包含 source=neon_form_summary、source_id、response_count、numeric_fields、notice 與 summary_id（聚合內容 SHA-256）。不向模型提供逐筆答案、原始時間、Email、其他未授權欄位或來源 URL。結果保留 form_summary／summary_id，local 模式另有統計 evidence。

目前 test/temp 僅連線測試，沒有業務定義；local 回報描述統計，不將其猜為活動偏好。模型須先呼叫工具，但尚未實作自然語言數字逐一核對，工具已被呼叫不代表整段模型文字一定正確。

不存在 workspace 或 DB 查詢錯誤直接失敗，不回退假摘要；有效 workspace 沒資料時回報 0 並提示先同步。新 API 工作只接受 neon_form_summary，前端原本省略來源欄位即可。舊等待工作即使保存 synthetic 標籤，新 worker 仍讀 Neon；已完成歷史不改寫。

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

真實 Neon → local Agent 唯讀驗證：2 筆；test 有效 2 筆、min=1、max=2、mean=1.5；temp 有效 2 筆、min=4、max=6、mean=5。該次僅讀資料庫，沒有讀 Apps Script、寫資料庫或呼叫付費模型。

最終離線測試：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_agent_runner tests.test_form_sync -v
```

13 項通過，涵蓋內容雜湊、格式與空列、來源限制、網路錯誤遮罩、欄位白名單、無效數值、資料改變影響結果、空資料、DB 失敗不回退、模型工具傳遞及 API 來源。另通過 compileall、git diff --check。

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
