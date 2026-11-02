# 內容提案與發布審核交接

## 交接範圍

本次新增的是「Strategy 到內容提案與排程資料」的流程，不包含人工審核、實際 Instagram 發布或成效回收。資料會保存在主平台的 Neon，不會把 OAuth token、Meta access token 或其他機密寫進內容提案。

先執行 migration `0007_content_draft_schedule`，再使用相關 API。

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
```

## 資料流程

```text
Strategy
  → Content Proposal Agent Run（輪播或單張）
  → Execution（WAITING_APPROVAL）
  → ExecutionAction（DRAFT 或 SCHEDULED）
  → Approval Request
  → APPROVED
  → 到達 scheduled_at 後由 worker 發布
  → EXECUTING → SUCCEEDED / FAILED
```

一份新的內容提案會建立一筆 `executions` 與初始 `execution_actions`。同一份提案的修改建立新 Action，舊 Action 會保留並改為 `SUPERSEDED`；不可覆寫舊內容。

### 提案版本規則

- 同一個 Strategy 下的新內容提案依序為 `v1`、`v2`、`v3`。
- 修改 `v1` 會依序產生 `v1.1`、`v1.2`；修改 `v2` 則為 `v2.1`。
- 提案名稱用於辨識不同提案；前端卡片只顯示短版版本，文案內容用於快速比較。

## 已提供的 API

所有端點均需 Bearer `PLATFORM_API_KEY`。

| 方法 | 端點 | 用途 |
| --- | --- | --- |
| `GET` | `/strategies` | 讀取可建立內容提案的 Strategy |
| `POST` | `/strategies/{strategy_id}/content-draft-runs` | 建立背景內容提案工作；worker 依格式產生並保存提案 |
| `POST` | `/strategies/{strategy_id}/content-drafts` | 手動建立內容提案；相同輸入會回傳既有提案，不重複建立 |
| `GET` | `/strategies/{strategy_id}/content-drafts` | 讀取指定 Strategy 的內容提案與版本 |
| `POST` | `/content-drafts/{action_id}/versions` | 以現有提案建立修改版本，原版本改為 `SUPERSEDED` |

背景產生內容提案的 request 範例：

```json
{
  "channel": "instagram",
  "content_format": "carousel",
  "scheduled_at": "2026-11-05T18:30:00+08:00"
}
```

`content_format` 可為 `carousel` 或 `single`。
`scheduled_at` 為選填，但設定時必須是含時區的未來時間。

手動建立內容提案的 request 範例：

```json
{
  "channel": "instagram",
  "title": "新手零基礎體驗輪播",
  "caption": "想親手完成一件作品嗎？來參加工作坊！",
  "hashtags": ["NTUMaker", "3D列印"],
  "image_requirements": [
    "1080×1080 封面，展示學生實作成品與活動資訊",
    "作品細節或活動流程照"
  ],
  "image_urls": ["https://public.example.com/workshop-cover.jpg"],
  "carousel": false,
  "scheduled_at": "2026-11-05T18:30:00+08:00"
}
```

規則：

- `scheduled_at` 有值時，Action 狀態為 `SCHEDULED`；沒有時為 `DRAFT`。
- `scheduled_at` 必須含時區。
- `image_urls` 必須是公開的 HTTPS 網址；尚未準備圖片時可留空，只保存 `image_requirements`。
- 輪播至少需要兩項素材需求；單張貼文只需要一項主視覺需求。
- 模型不得產生或猜測 `image_urls`。
- `hashtags` 會去除 `#`、空白與重複值。正式傳給 Meta 時，已合併至 caption 最後一段。
- 單張圖且 `carousel=false` 時，`payload.meta_adapter_payload` 會提供目前 `meta_api_test` 可直接使用的 `image_url` 與合併後 `caption`。
- 多張圖／輪播提案會保存在 `image_urls`，但目前 `meta_api_test` 尚未支援輪播，所以 `meta_adapter_payload` 為 `null`，不可發布。

## 後續人工審核與發布時應做的事

1. 建立 `approval_requests`，關聯 `execution_action_id`，並顯示內容提案的 caption、hashtags、圖片、渠道與 `scheduled_at`。
2. 只允許 Admin 將內容提案從 `DRAFT`／`SCHEDULED` 送入 `PENDING_REVIEW`、再核准為 `APPROVED`；拒絕則為 `REJECTED`。
3. worker 發布前再次確認：
   - action 是最新版本，不是 `SUPERSEDED`
   - approval 已為 `APPROVED`
   - `scheduled_at` 已到達，或沒有設定排程
   - `content_hash`、`idempotency_key` 沒有被修改
   - `oauth_connections` 的帳號授權仍有效
4. 只有上述條件全數成立，才把 `payload.meta_adapter_payload` 傳給 `meta_api_test`。不得把 token 傳到前端或寫入 `payload`。
5. 發布前設為 `EXECUTING`；成功設 `SUCCEEDED` 並寫入 `external_id`；失敗設 `FAILED`，保存可公開的錯誤碼與重試資訊，但不要保存 token 或完整第三方錯誤內容。
6. 同一個 `idempotency_key` 已發布成功時，必須直接回傳既有結果，禁止重複發布。

## 與 Agent Strategy 的銜接

Agent 建立 Strategy 時，應同步建立正式 `strategies` 紀錄並回傳 `strategy_id`、`goal_id`、`version`。內容提案只依賴 `strategy_id`；不應直接依賴 `AgentRun.output_payload` 的自由格式 JSON。

`AgentRun.output_payload` 可保留策略執行快照與資料來源；`strategies`、`executions`、`execution_actions` 才是發布閉環的正式關聯資料。當 output 含有 `strategy_id` 時，worker 會自動排入一筆預設為輪播的內容提案工作。

## 本機測試流程

先確認 migration 已套用，並分別啟動 API 與 worker。以下指令均在 CMD 執行：

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

開啟另一個 CMD 視窗：

```bat
cd backend
..\.venv\Scripts\python.exe -m app.agent_worker
```

再開啟第三個 CMD 視窗啟動前端：

```bat
cd frontend
npm run dev
```

開啟 `http://localhost:3000`。在 **連線設定** 填入：

- FastAPI URL：`http://127.0.0.1:8000`
- Development API key：`backend/.env` 的 `PLATFORM_API_KEY`

接著：

1. 在 **策略工作紀錄** 選擇一筆完成的策略工作；下方內容提案區會自動切換到該 Strategy。
2. 到 **Instagram 內容提案與排程**，選擇 **輪播貼文** 或取消勾選建立單張貼文；需要排程時，先選擇未來的預計發布時間。
3. 按 **由 Agent 產生輪播提案** 或 **由 Agent 產生單張提案**。
4. 按鈕顯示產生中；完成後，內容提案清單會自動新增一張提案卡片。內容提案工作不會出現在上方的策略工作紀錄。
5. 確認輪播提案有至少兩項素材需求、`image_urls` 為空，且模型沒有捏造圖片網址。
6. 按 **修改提案或設定排程**，變更文案、素材需求或排程時間後儲存；版本應由 `v1` 變成 `v1.1`，原版本狀態變為 `SUPERSEDED`。有未來發布時間的版本狀態為 `SCHEDULED`。
7. 對已排程的提案按 **取消排程**，系統會建立沒有 `scheduled_at` 的新版本並保留已排程版本；新版本狀態為 `DRAFT`。
8. 若要手動建立內容，填寫 **提案名稱**、文案、hashtags 與素材需求，再按 **儲存內容提案**；新提案會取得下一個主版本，例如 `v2`。

本機 `AGENT_PROVIDER=local` 即可驗證完整儲存與輪播資料流程，不需要模型 API key。切換到 Gemini、OpenAI 或 Claude 時，worker 才會依設定產生模型文案；key 只放 `backend/.env`，不可寫進 request、資料庫或文件。

### 以 API 測試排程與版本

以建立出的 `action_id` 呼叫 `POST /content-drafts/{action_id}/versions`，傳入更新內容與含時區的未來 `scheduled_at`：

```json
{
  "channel": "instagram",
  "title": "修改後的輪播提案",
  "caption": "修改後的輪播貼文文案。",
  "hashtags": ["NTUMaker", "創客"],
  "image_requirements": ["第 1 張封面", "第 2 張作品照", "第 3 張報名方式"],
  "image_urls": [],
  "carousel": true,
  "scheduled_at": "2026-12-01T18:30:00+08:00"
}
```

預期結果：新提案版本由 `v1` 變為 `v1.1`，Action 的 `draft_version` 增加、`status` 為 `SCHEDULED`；原版本保留且變為 `SUPERSEDED`。此測試只保存資料，不會發布到 Instagram。
