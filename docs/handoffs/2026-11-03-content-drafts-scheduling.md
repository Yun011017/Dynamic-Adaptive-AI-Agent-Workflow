# 內容草稿與排程交接

## 交接範圍與目前狀態

本次完成的是正式 Strategy 到 Instagram 內容草稿、版本與排程資料的保存流程。內容保存於主平台的 Neon；OAuth、Meta access token 與其他憑證不會進入前端、`ExecutionAction.payload` 或 Agent prompt。

已完成：內容草稿生成、手動建立、版本歷史、排程建立／取消、跨 Strategy 排程總覽，以及單張與輪播的 Meta adapter payload。

先套用 migration：

```bat
cd backend
python -m scripts.manage migrate
```

## 現有資料流程

```text
正式 Strategy
  → Content Proposal Agent Run（單張或輪播）
  → Execution（WAITING_APPROVAL）
  → ExecutionAction（DRAFT 或 SCHEDULED）
  → 使用者修改時建立新的 ExecutionAction 版本
  → 後續人工審核／發布模組接手
```

每個新提案建立一筆 `executions` 與初始 `execution_actions`。修改或由歷史版本回復時，會建立下一個 `draft_version`；目前可操作版本會被標成 `SUPERSEDED`，歷史資料不覆寫。

畫面版本號是 `提案主版本.修訂版本`，例如 `v2.5`；主版本來自 `payload.proposal_version`，修訂版本來自 `draft_version`。

## 已提供 API

所有端點均需 `Authorization: Bearer <PLATFORM_API_KEY>`。

| 方法 | 端點 | 用途 |
| --- | --- | --- |
| `GET` | `/strategies` | 讀取可用的正式 Strategy。 |
| `POST` | `/strategies/{strategy_id}/content-draft-runs` | 建立背景內容草稿工作。 |
| `POST` | `/strategies/{strategy_id}/content-drafts` | 手動建立內容草稿；相同輸入具冪等性。 |
| `GET` | `/strategies/{strategy_id}/content-drafts` | 讀取該 Strategy 下的提案及版本歷史。 |
| `GET` | `/content-drafts/scheduled` | 讀取目前 workspace 全部已排程提案。 |
| `POST` | `/content-drafts/{action_id}/versions` | 由任一歷史版本建立新的最新版本。 |

### 內容草稿契約

```json
{
  "channel": "instagram",
  "title": "新手零基礎體驗輪播",
  "caption": "想親手完成一件作品嗎？來參加工作坊！",
  "hashtags": ["NTUMaker", "3D列印"],
  "image_requirements": ["第 1 張封面", "第 2 張作品照"],
  "image_urls": [],
  "carousel": true,
  "scheduled_at": "2026-11-05T18:30:00+08:00",
  "schedule_requested": true
}
```

- `scheduled_at` 是發布規劃，需為含時區且晚於目前時間的時間；它本身不會使草稿變成已排程。
- `schedule_requested: true` 才會建立 `SCHEDULED` Action；未傳或為 `false` 則為 `DRAFT`。
- 輪播至少要兩項 `image_requirements`。若有提供輪播 `image_urls`，至少需兩張且全部是公開 HTTPS 網址。
- Agent 可產生 `image_requirements`，不得猜測或杜撰 `image_urls`。
- `hashtags` 保存時會去除 `#`、空白與重複值；輸出給 Meta 時才會合併進 caption。

## 給「產生 Strategy」負責人的整合資訊

內容草稿只依賴正式的 `strategies` 資料，不讀取 `AgentRun.output_payload` 的自由格式文字。

1. Strategy worker 成功後，必須先寫入 `strategies`，並在 `AgentRun.output_payload` 回傳至少 `strategy_id`、`goal_id`、`strategy_version`。
2. `strategy_id` 必須與同一 workspace 的正式 Strategy 對應；內容草稿會讀取該筆 `Strategy.content`、`Strategy.rationale`、其 Goal 與版本。
3. 同一 Goal 重新產生 Strategy 時應新增版本，不可覆寫舊 Strategy；舊 Strategy 的提案必須仍可讀取。
4. 現在的 agent worker 在 Strategy output 含有效 `strategy_id` 時，會自動排入一筆預設輪播的內容草稿工作。這個排入行為只在 Strategy worker 成功後發生。
5. Content draft worker 不會同步表單或再次生成 Strategy；它只使用已保存的 Strategy，避免資料來源在流程中改變。

交付前請確認 Strategy output 具有上述識別欄位，且 `strategies` 已成功寫入；否則不應把內容草稿視為可用。

## 給「人工審核、執行發布」負責人的整合資訊

請以 `ExecutionAction` 作為審核與發布的唯一動作單位，不要由前端草稿文字直接發文。

1. 新增 `approval_requests`（或等效資料模型），以 `execution_action_id` 關聯要審核的版本，並顯示 `payload` 中的 caption、hashtags、圖片、channel、`scheduled_at`。
2. 只有最新且非 `SUPERSEDED` 的 `DRAFT`／`SCHEDULED` Action 可送審；狀態流應為 `PENDING_REVIEW → APPROVED → EXECUTING → SUCCEEDED / FAILED`，拒絕為 `REJECTED`。
3. 發布 worker 在呼叫 adapter 前必須確認：已核准、不是 `SUPERSEDED`、若為排程則 `scheduled_at` 已到、`content_hash` 與 `idempotency_key` 未被改動、帳號授權有效。
4. 僅可將 `payload.meta_adapter_payload` 傳入目前的 `meta_api_test`；token 由 OAuth connection 管理，絕不可放入 payload 或前端。
5. `meta_adapter_payload` 在單張時會提供 `media_type: IMAGE`、`image_url` 與合併 hashtags 的 `caption`；輪播且有至少兩張公開 HTTPS 圖片時，會提供 `media_type: CAROUSEL`、`children` 與 `caption`。這是尚未發布的 adapter 輸入資料。
6. Meta 官方 Instagram Content Publishing API 支援 2 至 10 張圖／影片的 carousel：發布端須先為每個 `children` 項目建立 `is_carousel_item=true` 的 child container，再以 `media_type=CAROUSEL` 與 child IDs 建立 parent container，最後以 parent `creation_id` 呼叫 `media_publish`。接手者須保存每個 container ID、等待 container 就緒並維持整組操作的 idempotency。
7. 成功後寫入 `external_id` 並將狀態設為 `SUCCEEDED`；失敗設 `FAILED`，只保存安全的錯誤碼與重試資訊。相同成功的 `idempotency_key` 不得重複發布。

### 發布 worker 的輸入／輸出契約

發布 worker 應以 `ExecutionAction` 讀取工作，不要重新從前端組裝貼文。它至少需要：

```json
{
  "action_id": 42,
  "workspace_id": 1,
  "execution_id": 19,
  "status": "SCHEDULED",
  "content_hash": "sha256...",
  "idempotency_key": "sha256...",
  "payload": {
    "channel": "instagram",
    "scheduled_at": "2026-11-05T18:30:00+08:00",
    "meta_adapter_payload": {
      "media_type": "CAROUSEL",
      "caption": "貼文文字\n\n#NTUMaker",
      "children": [
        {"image_url": "https://public.example.com/1.jpg", "is_carousel_item": true},
        {"image_url": "https://public.example.com/2.jpg", "is_carousel_item": true}
      ]
    }
  }
}
```

單張貼文的 `meta_adapter_payload` 則是：

```json
{
  "media_type": "IMAGE",
  "image_url": "https://public.example.com/cover.jpg",
  "caption": "貼文文字\n\n#NTUMaker"
}
```

發布成功後，worker 必須將 Meta 回傳的貼文 ID 寫入 `ExecutionAction.external_id`，並將狀態更新為 `SUCCEEDED`；失敗時更新為 `FAILED`。審核資料、child container IDs 與安全的錯誤／重試資訊應由發布方新增的資料表保存，不能覆寫原始 `payload`。

## 驗證方式

```bat
cd backend
python -m scripts.manage migrate
python -m unittest discover -s tests -v
```

主要測試涵蓋內容草稿的冪等性、版本增加、`SCHEDULED`／`DRAFT` 狀態與跨 workspace 隔離，見 `backend/tests/test_platform.py` 的 `test_15_content_drafts_are_versioned_scheduled_and_idempotent`。

本機以 `AGENT_PROVIDER=local` 即可驗證草稿生成與保存；不需要模型 API key。切換至 Gemini、OpenAI 或 Claude 時，憑證僅放在 `backend/.env`。

## 已知限制

- 已排程不等於已核准，也不會在時間到時自動發布。
- Meta 官方 API 支援 carousel；本模組已產生輪播 adapter payload，但實際建立 containers 與發布仍屬發布 worker 的工作。
- 未建立 `approval_requests` 或發布 worker；這是人工審核、執行發布的實作範圍。
