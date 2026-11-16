# Instagram 素材儲存與生命週期

Instagram 內容提案的圖片與影片儲存在 Cloudflare R2，並以公開 HTTPS 網址供貼文預覽、人工審核與 Meta 發文讀取。網站本身維持部署於 [Vercel](https://dynamic-adaptive-ai-agent-workflow.vercel.app/)。

## 公開素材網域

所有素材都從下列自有子網域提供：

```text
https://media.dynamic-adaptive-ai-agent-workflow.fengyenchen.com
```

素材網址是資料庫內容提案中保存的正式網址，因此網址必須持續公開，不能改成需要登入、短期簽名或只限內網存取的連結。

## 存放路徑

每筆上傳都會產生不可預測的 UUID 檔名，避免覆蓋同名檔案；使用者原始檔名不會出現在公開網址中。

| 素材 | R2 object key | 公開網址形式 |
| --- | --- | --- |
| 圖片 | `workspaces/{workspace_id}/instagram/images/{uuid}.jpg` | `https://media.dynamic-adaptive-ai-agent-workflow.fengyenchen.com/workspaces/{workspace_id}/instagram/images/{uuid}.jpg` |
| 影片 | `workspaces/{workspace_id}/instagram/videos/{uuid}.mp4` | `https://media.dynamic-adaptive-ai-agent-workflow.fengyenchen.com/workspaces/{workspace_id}/instagram/videos/{uuid}.mp4` |

`workspace_id` 是系統目前工作空間的資料庫編號，例如 `workspaces/2/...` 代表編號為 2 的工作空間，並非使用者輸入或社群帳號編號。

## 上傳與保存流程

1. 使用者在 Instagram 內容提案選取圖片或影片。
2. 後端建立 15 分鐘有效的一次性 R2 上傳表單；檔案由瀏覽器直接上傳 R2，不經過 Vercel 函式。若瀏覽器直傳暫時不可用，小於 4 MB 的素材會改用後端備援上傳。
3. 上傳完成後，後端重新檢查檔案大小、MIME 類型與檔頭，再將公開網址填入提案編輯欄位。
4. 使用者按「建立新版本」或保存內容提案時，該素材會標記為已引用並永久保留，隨內容提案版本供審核、排程與 Meta 發布使用。

這個流程避免大檔案受到 Vercel HTTP 請求大小與執行時間限制；單檔大小由 `R2_MAX_UPLOAD_BYTES` 控制，預設 100 MB。需要大型影片時可提高此值，最高為 5 GiB（仍應配合 Meta 對影片格式與檔案大小的限制）。

## 未保存素材的清理

剛上傳但尚未被內容提案保存的素材會登錄為暫存素材。預設保留 24 小時；若使用者沒有保存提案，系統每日會刪除 R2 物件及其暫存紀錄。保存後的素材不會被此清理程序刪除。

保留時間由 `MEDIA_UPLOAD_TTL_HOURS` 控制。清理工作由部署端每日呼叫 `/internal/media/cleanup`，不會公開給一般使用者。

## 支援格式與限制

- 圖片：JPG、PNG、WebP
- 影片：MP4、MOV
- 預設單檔上限：100 MB；直傳失敗時，後端備援僅接受 4 MB 以下素材。
- 上傳完成後會再次驗證實際檔案內容；檔名或 MIME 宣稱與檔案內容不一致時會拒絕並清除。

瀏覽器直接上傳需要 R2 公開素材網域允許本網站與本機開發站的跨網域上傳；這是 R2 bucket 的既有存取設定之一，而非素材網址本身的公開讀取設定。
