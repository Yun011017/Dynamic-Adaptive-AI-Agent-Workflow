# 社團正式報名表單、活動來源管理與 Execution 綁定交接

## 1. 交接基準

- 日期：2026-11-21，Asia/Taipei。
- 功能提交：`5b67c49`（`feat: manage activity form sources and execution bindings`）。
- 整合提交：`8c4b26d`（`Merge latest main with activity form management`）。
- 已推送並確認遠端 `main`、`dengdee` 均指向 `8c4b26d3f410c255135fac92f10e8fa8531ac8b7`；目前本機分支為 `dengdee`。
- 合併保留了遠端同期新增的內容提案歷史與發布狀態紀錄；沒有強制推送。
- 本交接文件在上述功能整合提交之後新增，文件提交雜湊以 Git 歷史為準。
- 已完成原設定 Neon 的 migration 至 `0014`。已推送原始碼，但尚未確認推送後的 Vercel 自動部署與 GitHub Actions 正式執行結果，不能視為線上驗收完成。

## 2. 完成內容與使用流程

前端「內容提案」選擇策略後，新增「報名表單綁定」面板：

1. 按「新增表單」，輸入名稱、Apps Script `/exec` 部署網址及試算表時區。
2. 來源自動歸屬目前策略的 Goal；沒有 Execution 時也可先新增來源。
3. 按「同步回覆」，將 Google 回覆寫入 Neon，顯示讀取、新增與既有筆數。
4. 選擇該策略的 Execution，再選人工／AI 表單來源，按「儲存綁定」。
5. 儲存時補齊既有未關聯回覆，後續同步自動沿用資料庫綁定，不必修改 `GOOGLE_FORMS_EXECUTION_MAP`。

每個來源可以啟用／停用；停用會停止同步與新綁定，保留既有回覆與關聯。多個活動來源可同時存在。Worker 依該次工作 Goal 同步來源，Agent 摘要與資料依據依活動篩選；觀測資料也依其 Strategy／Execution 所屬 Goal 篩選。

Execution 是一次策略執行紀錄。現有內容提案流程會建立 Execution，尚未提供專供系統外人工貼文使用的「直接建立執行紀錄」前端操作；已有建立 Execution 的 API。

## 3. 正式表單契約與欄位

目前支援 Apps Script 回傳以下分組物件；範例皆為合成資料：

```json
{
  "success": true,
  "data": {
    "人工": [{
      "時間戳記": "2026/11/21 上午 10:30:00",
      "電子郵件地址": "member@example.test",
      "姓名": "測試社員",
      "是否是社員": "是"
    }],
    "ai": []
  }
}
```

也保留第一列為欄名的二維陣列格式。新登記來源若使用二維陣列，應包含「文案來源」欄位，值為 `人工` 或 `ai`，才能區分並綁定。Google 表單填寫連結與 Sheets 編輯連結不能當作 Apps Script 資料端點。

| 原始資訊 | `form_responses` 欄位 | 規則 |
| --- | --- | --- |
| 時間戳記 | `submitted_at` | 轉 UTC；無時區資料使用該來源設定的時區。 |
| 電子郵件地址 | `email` | 保存在資料庫，不加入 Agent 摘要。 |
| 姓名 | `respondent_name` | 保存在資料庫，不加入 Agent 摘要。 |
| 是否是社員 | `is_member` | 是／否轉 boolean；缺漏與未知值為 NULL。 |
| 參加意願題目 | `will_attend` | 依使用者要求，缺題或空白預設 true；明確否定為 false，未知非空答案為 NULL。 |
| 人工／ai 分組 | `copy_source` | 分組匯入時補入「文案來源」。 |
| 邏輯來源 | `source_id` | 來源的固定識別，不是 Google 表單 ID。 |
| 執行紀錄 | `execution_id` | 綁定後補上；未綁定為 NULL。 |

時間支援含時區 ISO 8601、無時區 ISO、`YYYY/MM/DD HH:mm:ss` 及中文上午／下午格式。已測試上午／下午 12 點邊界；新來源時區預設 `Asia/Taipei`。缺少有效時區或日期格式錯誤時，時間為 NULL 並記錄正規化錯誤。

原始答案仍存於 `external_events.raw_payload.answers`；`fetched_at` 是擷取時間。Agent 僅取得結構化摘要，不取得姓名、Email、原始答案或來源網址。

## 4. 資料庫與歸因規則

| Migration | 變更 |
| --- | --- |
| `0012_form_registration_attribution` | `form_responses` 增加 email、respondent_name、copy_source、execution_id 與跨工作區保護外鍵。 |
| `0013_form_execution_bindings` | 新增 `form_execution_bindings`，保存 workspace＋source_id＋copy_source → Execution。 |
| `0014_form_sources` | 新增 `form_sources`，保存名稱、固定 source_id、Goal、Apps Script 網址、時區與 enabled。 |

注意：遠端原本已有 `0011_media_assets`；表單欄位 migration 已接在其後，不能使用早期討論中的重複 `0011` 編號。

- `form_sources` 的活動與網址建立後固定，沒有編輯／刪除 API。
- 同一工作區不允許重複登記相同網址；來源識別自動產生。
- 綁定單位是 workspace＋source_id＋人工／ai，每組只能歸屬一個 Execution。跨工作區、跨活動或重新歸因會拒絕。
- 資料庫綁定優先於舊環境變數；登記來源同步不套用全域 `GOOGLE_FORMS_EXECUTION_MAP`，避免新活動沿用舊 Execution。
- 匯入、來源設定與綁定操作以 workspace row lock 序列化；綁定與既有回覆補齊在同一交易完成。
- 等待 Google 時不持有資料庫交易。多來源同步每個來源各自交易；後面來源失敗不會回滾前面已成功來源，Worker 會回報同步失敗並讀取已保存資料。

## 5. API 與主要檔案

所有端點沿用後端 API key 與 workspace 驗證。

| API | 用途 |
| --- | --- |
| `GET /form-source-configs` | 列出登記來源，不回傳 Apps Script 網址。 |
| `POST /form-source-configs` | 建立來源，接收 name、goal_id、apps_script_url、timezone。 |
| `PATCH /form-source-configs/{id}` | 設定 enabled。 |
| `POST /form-source-configs/{id}/sync` | 同步單一來源，回傳 read／inserted／skipped。 |
| `GET /form-sources` | 列出可綁定組別、回覆數與 Execution，不回傳個資。 |
| `GET /strategies/{id}/executions` | 列出策略下的執行紀錄。 |
| `POST /executions/{id}/form-bindings` | 接收 source_id、copy_source，建立綁定並補齊舊回覆。 |

實作位置：

- `backend/app/form_sources.py`：來源建立、舊來源承接、單一來源同步與活動來源篩選。
- `backend/app/form_bindings.py`：來源組別清單、Execution 綁定、回覆補齊。
- `backend/app/form_sync.py`、`form_fields.py`：傳輸、格式解析、去重、正規化與寫入。
- `backend/app/form_summary.py`、`agent_runner.py`、`agent_worker.py`：依 Goal 同步與分析。
- `backend/app/main.py`、`schemas.py`、`models.py`：API、驗證與模型。
- `frontend/app/form-binding-panel.tsx`：新增來源、同步、啟用／停用、綁定介面。
- `frontend/app/dashboard.tsx`：面板整合與活動／Execution 顯示。

## 6. 既有資料與相容模式

本次最後一次正式 API 驗證結果：已登記來源 0 個，保留舊單來源回覆 3 筆（人工 1、ai 2）。此為交接前快照，不代表未來即時筆數。三筆的參加意願均已同步為 true；當時尚未綁定 Execution。

舊設定 `GOOGLE_FORMS_SOURCE_ID=club-copy-ab-2026-11` 是本次人工／AI 測試的邏輯來源標籤，不包含可供程式推導的活動關聯。

- 工作區還沒有 `form_sources` 時，沿用 `.env` 單來源模式。
- 登記第一個來源後，活動同步與摘要改以登記資料為準；未登記的舊來源不會混入活動分析。
- 若在正確活動下新增的網址與目前 `.env` 網址相同，會承接舊 source_id，保留回覆與去重身份。既有綁定或已關聯回覆屬於其他活動時拒絕承接。
- 因此，接手者應先確認原表單屬於哪個 Goal，再於該活動下登記原網址，不能任意選活動承接。

## 7. 環境、憑證與啟動

- 本機設定位於 `backend/.env`，已被 Git 忽略且未提交；勿將其內容複製至文件或前端。
- 沿用 `DATABASE_URL`、`MIGRATION_DATABASE_URL`、`PLATFORM_API_KEY`、`PLATFORM_WORKSPACE_SLUG`；資料庫登記來源不需在 `.env` 新增個別網址。
- 舊單來源使用 `GOOGLE_FORMS_APPS_SCRIPT_URL`、`GOOGLE_FORMS_SOURCE_ID`、`GOOGLE_FORMS_NAIVE_TIMEZONE`。`GOOGLE_FORMS_EXECUTION_MAP` 僅保留相容用途。
- 題目名稱仍使用全域 `GOOGLE_FORMS_*_COLUMN` 設定，尚無每來源自訂欄位對照。
- 本機後端使用專案 `.venv` 的 Python 3.12.9；即使 PowerShell 提示列顯示 `.venv-py314-backup`，以下明確指定的執行檔仍使用 `.venv`。
- 同步遠端後曾缺少 boto3；已依 requirements 補裝 boto3 1.40.61、python-multipart 及其依賴。
- GitHub Actions worker 使用 `.github/workflows/agent-worker.yml`；Secrets／Variables 與 Vercel 設定需各自確認，不會因本機 `.env` 合併而自動同步。

在 backend 目錄執行：

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

另開終端執行 `..\.venv\Scripts\python.exe -m app.agent_worker --once` 處理一筆待執行工作，或 `..\.venv\Scripts\python.exe -m app.form_worker` 同步目前工作區的啟用來源。前端於 frontend 目錄執行 `npm run dev`。

## 8. 驗證與已知限制

已完成：

- 48 項表單／Agent 離線測試通過；整合遠端發布紀錄後，連同發布紀錄測試共 50 項通過。
- PostgreSQL 隔離 schema 驗證欄位寫入、綁定補齊、後續匯入優先序、來源新增與去重、多活動／workspace 隔離、停用、日期時區、migration metadata 一致性、Agent 流程及失敗回退。
- `npx tsc --noEmit`、`npm run build`、Git diff whitespace 檢查通過；整合遠端更新後也重新完成前端建置。
- 正式 Apps Script 曾成功讀取並匯入；原設定 Neon 已套用至 `0014`，新來源清單 API 回傳 200，原有 3 筆回覆仍保留。
- 未進行新面板的瀏覽器端完整操作驗收，也未替使用者選定活動來源或 Execution。

離線測試（backend 目錄）：

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_form_sources tests.test_form_fields tests.test_registration_import tests.test_form_sync tests.test_agent_runner tests.test_agent_worker tests.test_publishing_audit -q
```

PostgreSQL 測試在 `tests.test_platform`，會建立隨機 `platform_test_*` schema 並在完成後清理；必須使用支援 startup search_path 的直接連線，不能拿一般測試清理指令刪除正式資料表。測試固定 local 模型，不呼叫付費模型。

限制：

- 仍以答案內容雜湊去重；同來源完全相同答案會合併，修改答案或欄位集合可能形成新事件，來源刪除不會刪除已匯入資料。尚無穩定 Google response ID 或更新／刪除歷程。
- 同一個表單來源不應跨活動或宣傳輪次共用，否則無法可靠區分成效。
- Execution 關聯代表報名入口歸屬，不能證明填表者確實看過指定貼文。
- 尚未自動將報名數建立為 KPI Observation，也沒有流量／點擊分母或轉換率計算。
- API key 仍為開發階段權限機制，不是正式登入與角色授權。

## 9. 下一位可直接開始的工作

1. 確認原表單的 Goal，於新介面登記原 Apps Script 網址並驗證承接後仍為原三筆，不產生重複資料。
2. 依人工與 AI 貼文確認 Execution，再分別綁定；系統外人工貼文若無提案，評估新增「直接建立執行紀錄」介面。
3. 用兩個活動完成瀏覽器驗收：新增、同步、切換活動、綁定、停用／啟用，確認錯誤提示與資料隔離。
4. 查核 main 推送後的 Vercel 建置及 GitHub Actions，確認線上後端／worker 連到已升級資料庫；本次尚未完成部署監看。
5. 若需成效評估，先定義有效報名／去重與觀測期間，再實作按 Execution 彙總的 Observation；不要將全部工作區回覆直接算成某篇貼文的成效。
