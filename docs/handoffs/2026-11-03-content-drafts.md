# 內容草稿與發布審核交接

## 交接範圍

本次新增的是「Strategy 到內容草稿與排程資料」的第一段，不包含人工審核、實際 Instagram 發布或成效回收。資料會保存在主平台的 Neon，不會把 OAuth token、Meta access token 或其他機密寫進草稿。

先執行 migration `0007_content_draft_schedule`，再使用相關 API。

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.manage migrate
```

## 資料流程

```text
Strategy
  → Execution（WAITING_APPROVAL）
  → ExecutionAction（DRAFT 或 SCHEDULED）
  → Approval Request
  → APPROVED
  → 到達 scheduled_at 後由 worker 發布
  → EXECUTING → SUCCEEDED / FAILED
```

一個內容草稿就是一筆 `execution_actions`。建立新版本時，舊草稿會保留，但狀態改為 `SUPERSEDED`；不可覆寫舊內容。

## 已提供的 API

所有端點均需 Bearer `PLATFORM_API_KEY`。

| 方法 | 端點 | 用途 |
| --- | --- | --- |
| `GET` | `/strategies` | 讀取可建立草稿的 Strategy |
| `POST` | `/strategies/{strategy_id}/content-drafts` | 建立內容草稿；相同輸入會回傳既有草稿，不重複建立 |
| `GET` | `/strategies/{strategy_id}/content-drafts` | 讀取指定 Strategy 的草稿版本 |
| `POST` | `/content-drafts/{action_id}/versions` | 以現有草稿建立下一版本，原版本改為 `SUPERSEDED` |

建立草稿的 request 範例：

```json
{
  "channel": "instagram",
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

- `scheduled_at` 有值時，草稿狀態為 `SCHEDULED`；沒有時為 `DRAFT`。
- `scheduled_at` 必須含時區。
- `image_urls` 必須是公開的 HTTPS 網址；尚未準備圖片時可留空，只保存 `image_requirements`。
- `hashtags` 會去除 `#`、空白與重複值。正式傳給 Meta 時，已合併至 caption 最後一段。
- 單張圖且 `carousel=false` 時，`payload.meta_adapter_payload` 會提供目前 `meta_api_test` 可直接使用的 `image_url` 與合併後 `caption`。
- 多張圖／輪播草稿會保存在 `image_urls`，但目前 `meta_api_test` 尚未支援輪播，所以 `meta_adapter_payload` 為 `null`，不可發布。

## 後續人工審核與發布時應做的事

1. 建立 `approval_requests`，關聯 `execution_action_id`，並顯示草稿的 caption、hashtags、圖片、渠道與 `scheduled_at`。
2. 只允許 Admin 將草稿從 `DRAFT`／`SCHEDULED` 送入 `PENDING_REVIEW`、再核准為 `APPROVED`；拒絕則為 `REJECTED`。
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

Agent 建立 Strategy 時，應同步建立正式 `strategies` 紀錄並回傳 `strategy_id`、`goal_id`、`version`。內容草稿只依賴 `strategy_id`；不應直接依賴 `AgentRun.output_payload` 的自由格式 JSON。

`AgentRun.output_payload` 可保留策略執行快照與資料來源；`strategies`、`executions`、`execution_actions` 才是發布閉環的正式關聯資料。
