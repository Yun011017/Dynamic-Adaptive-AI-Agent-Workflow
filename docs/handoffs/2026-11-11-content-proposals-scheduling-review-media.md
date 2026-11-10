# 內容提案、排程審核與影音素材交接

## 範圍

本次工作涵蓋 Instagram 內容提案製作、先設定發布時間再送交人工審核，以及影音素材資料與發布契約。內容提案現在可選擇四種貼文形式，素材需求與公開網址會隨形式切換；只有資料完整的提案才可送交人工審核。

| 貼文形式 | 送審前必填內容 |
| --- | --- |
| 單張圖片貼文 | 一項圖片素材需求、一張公開 HTTPS 圖片網址。 |
| 多張圖片貼文 | 至少兩項圖片素材需求、至少兩張公開 HTTPS 圖片網址。 |
| 單支影片貼文（Reel） | 一項影音素材需求、一支公開 HTTPS 影片網址。 |
| 圖片＋影片貼文 | 圖片與影音素材需求皆至少一項，圖片與影片網址皆至少一個；兩種素材數量都可增加。 |

流程為：填寫素材與發布時間 → 送交人工審核 → 核准後才成為 `SCHEDULED` → 發布 worker 在時間到達後執行。

## 發文 API 負責人需要做的事

請以 `ExecutionAction.payload.meta_adapter_payload` 作為唯一發文輸入，不要由前端重新拼接資料，也不要把 access token 寫入 payload。

1. 確認 Meta 發文帳號是可發布的 Instagram 專業帳號，並具備 `instagram_content_publish` 權限。
2. 發布前再次確認 Action 是 `SCHEDULED`、排程時間已到、最新 Approval 為 `APPROVED`，且 `content_hash` 與 Approval 保存值相同。
3. 依下列 `media_type` 建立 Meta container：
   - `IMAGE`：以 `image_url` 建立單張圖片 container。
   - `REELS`：以 `media_type=REELS` 與 `video_url` 建立 Reel container；必須等待 Meta 回傳 `status_code=FINISHED` 才能發布。
   - `CAROUSEL`：先逐一建立 `children` child container，再以 child IDs 建立 parent container；影片 child 要指定 `media_type=VIDEO`、`video_url`，並等待處理完成後才建立 parent。
4. 以 parent 或單一 container ID 呼叫 `media_publish`；成功後寫入 `ExecutionAction.external_id` 並改為 `SUCCEEDED`。失敗改為 `FAILED`，保存安全的錯誤碼與重試資訊。
5. 以 `idempotency_key` 防止同一份 Action 重複發布；不得重複呼叫 Meta 建立相同成功貼文。

## Adapter 輸入契約

### 單張圖片貼文

```json
{
  "media_type": "IMAGE",
  "image_url": "https://public.example.com/cover.jpg",
  "caption": "貼文文字\n\n#NTUMaker"
}
```

### 多張圖片貼文

```json
{
  "media_type": "CAROUSEL",
  "caption": "貼文文字\n\n#NTUMaker",
  "children": [
    {"media_type": "IMAGE", "image_url": "https://public.example.com/1.jpg", "is_carousel_item": true},
    {"media_type": "IMAGE", "image_url": "https://public.example.com/2.jpg", "is_carousel_item": true}
  ]
}
```

### Reel

```json
{
  "media_type": "REELS",
  "video_url": "https://public.example.com/reel.mp4",
  "caption": "貼文文字\n\n#NTUMaker"
}
```

### 圖片＋影片貼文

```json
{
  "media_type": "CAROUSEL",
  "caption": "貼文文字\n\n#NTUMaker",
  "children": [
    {"media_type": "IMAGE", "image_url": "https://public.example.com/1.jpg", "is_carousel_item": true},
    {"media_type": "VIDEO", "video_url": "https://public.example.com/process.mp4", "is_carousel_item": true}
  ]
}
```

所有圖片與影片網址都必須可被 Meta 伺服器讀取的公開 HTTPS URL，不能使用電腦本機路徑、需要登入的 URL 或暫時失效的連結。

## 目前程式位置

- 草稿資料、素材驗證與 Meta payload：`backend/app/schemas.py`、`backend/app/content_drafts.py`
- Agent 內容生成提示詞：`backend/app/content_generator.py`
- 審核門檻與排程轉換：`backend/app/services/approval_service.py`
- Meta 發布與影片 container 等待：`backend/app/services/publisher_service.py`
- 排程 worker：`backend/app/agent_worker.py`
- 前端內容提案與待審核詳情：`frontend/app/dashboard.tsx`

## 環境變數與憑證

僅在 `backend/.env` 或部署環境設定，禁止出現在前端、commit、log 或 `ExecutionAction.payload`：

```text
META_ACCESS_TOKEN=...
META_IG_USER_ID=...
GRAPH_API_VERSION=...
```

## 驗證方式

```bat
cd frontend
npx tsc --noEmit

cd ..\backend
..\.venv\Scripts\python.exe -m unittest tests.test_content_drafts tests.test_content_generator tests.test_approval_publish -v
```

再以 Meta 測試帳號逐一驗證四種形式。影片與圖片＋影片貼文必須驗證 container 處理等待、排程時間未到時不發布、核准後才出現在「已加入排程」。

## 已知限制

- Meta 實際帳號授權、發布額度與媒體格式限制仍需由發布 API 負責人以測試帳號驗收。
- 本次變更尚未提交；提交後請在此補上對應 commit。
