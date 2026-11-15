# 待審核貼文佇列與 Instagram 影片發布交接

## 完成內容

- `GET /approval-requests` 在同一 workspace 內，透過 Action → Execution → Strategy → Goal 取得活動名稱，以 `campaign_name` 回傳。待審卡片標題顯示活動名稱、貼文主題及草稿版本（例如 `v2.3`）。
- 展開待審卡片可查看完整文案、Hashtag、圖片與影片素材需求，以及台北時間的預計發布時間。素材預覽沿用 Instagram 內容提案的圖片與影片播放器。
- 建立和修訂草稿均支援 `video_url`。省略 `post_format` 時會建立 Reel 草稿。後端將單一網址轉為既有的 `video_urls` 陣列，並產生含 `video_url` 的 Meta Reel 發布資料。若同時傳入兩欄，`video_urls` 必須只包含同一個網址。

## API 與發布流程

以 `POST /strategies/{strategy_id}/content-drafts` 建立草稿，或以 `POST /content-drafts/{action_id}/versions` 建立修訂版。以下以單支影片為例，送審前應把範例網址和時間替換為實際可公開讀取的 HTTPS 影片及未來時間。

```json
{
  "title": "工作坊活動花絮",
  "caption": "一起回顧這次工作坊",
  "video_requirements": ["直式活動花絮"],
  "video_url": "https://cdn.example.com/reel.mp4",
  "scheduled_at": "2026-12-01T18:00:00+08:00"
}
```

1. 以 `POST /actions/{action_id}/approval-requests` 送審。後端會檢查發布時間、素材需求和影片是否能公開讀取。
2. 以 `POST /approval-requests/{approval_id}/decision` 傳入 `{"decision":"approved"}`。核准後 Action 進入 `SCHEDULED`，由排程 worker 在時間到達後發布。
3. 到期後也可透過 `POST /actions/{action_id}/execute` 手動觸發。可省略 body，或提供 `{"video_url":"https://cdn.example.com/reel.mp4"}`。若提供網址，須與已核准的 Reel 完全一致，否則回傳 409。更換素材時須建立新版本並重新送審。
4. 發布時依既有流程檢查核准和內容雜湊，再透過 Meta Graph API 建立 Reel 容器，待 `status_code=FINISHED` 後呼叫 `media_publish`。成功後 Action 會保存 Meta 回傳的 `external_id`，並更新為 `SUCCEEDED`。

## 環境與憑證

- 本機後端設定由 `backend/.env` 載入。API 與資料庫使用 `PLATFORM_API_KEY`、`PLATFORM_WORKSPACE_SLUG`、`DATABASE_URL`。
- Meta 發布設定使用 `META_IG_USER_ID`、`META_ACCESS_TOKEN`、`GRAPH_API_VERSION`。部署時由後端或 worker 的環境設定注入。API 請求只包含影片網址，憑證由伺服器讀取。
- 這次變更沿用既有資料表與 JSON payload，無需新增 migration。

## 驗證與下一步

從 `backend` 目錄使用已安裝相依套件的 Python 執行：

```powershell
python -m unittest discover -s tests -p test_content_drafts.py
python -m unittest discover -s tests -p test_approval_publish.py
```

- 草稿測試 8 項、發布測試 6 項通過。發布測試使用模擬 Meta 回應，驗證不符的網址不會送出請求，並確認 Reel 容器建立、狀態查詢及發布的順序。
- 待審佇列通過前端 TypeScript 型別檢查及本機 SQLite 查詢驗證。完整後端整合測試曾因設定的資料庫主機名稱無法解析而未完成。
- 尚待使用測試用 Instagram 帳號與公開影片，在部署環境驗證一次完整流程。可先確認待審卡片顯示正確的活動、版本、文案和時間，再核准並於到期後檢查 Action 的 `external_id` 與 Instagram 發布結果。

## 分支與提交

- 分支為 `codex/approval-queue-details`。
- 待審核佇列改動已隨 `f1202c1` 推送至同名遠端分支。
- `video_url` API 改動與本交接文件收錄在同一筆提交。
