# Cloudflare R2 素材上傳與 Instagram 內容提案

## 本次完成範圍

Instagram 內容提案現在支援使用者自行上傳素材：

- 圖片：JPG、PNG、WebP
- 影片：MP4、MOV
- 上傳成功後，後端將檔案存入 Cloudflare R2，回傳公開 HTTPS 網址。
- 前端會自動把網址補進「公開圖片網址」或「公開影片網址」欄位，因此後續貼文預覽、人工審核、排程與 Meta 發文都使用同一個網址。
- AI 生圖／影片尚未納入本次範圍。

## 實作位置

| 位置 | 用途 |
| --- | --- |
| `backend/app/services/media_storage.py` | 產生直傳 R2 表單、驗證上傳物件、清理未保存素材。 |
| `POST /media/uploads/presign` | 受 Development API key 保護，建立短期 R2 直傳表單。 |
| `POST /media/uploads/{asset_id}/complete` | 驗證 R2 物件後回傳可保存的公開網址。 |
| `frontend/app/dashboard.tsx` | Instagram 內容提案的圖片／影片選檔上傳介面。 |
| `backend/app/config.py` | R2 環境變數與最大檔案大小設定。 |
| `docs/Cloudflare-R2-素材儲存說明.md` | 素材網域、路徑與生命週期說明。 |

每個檔案的 R2 key 會使用下列前綴，避免不同 workspace 的素材混在一起：

```text
workspaces/{workspace_id}/instagram/images/{uuid}.jpg
workspaces/{workspace_id}/instagram/videos/{uuid}.mp4
```

## R2 儲存路徑與網址對照

檔案實際存放在已設定的 R2 bucket，物件 key 與對外網址的關係如下：

| 素材 | R2 object key | 公開網址範例 |
| --- | --- | --- |
| 圖片 | `workspaces/1/instagram/images/{uuid}.jpg` | `https://media.dynamic-adaptive-ai-agent-workflow.fengyenchen.com/workspaces/1/instagram/images/{uuid}.jpg` |
| 影片 | `workspaces/1/instagram/videos/{uuid}.mp4` | `https://media.dynamic-adaptive-ai-agent-workflow.fengyenchen.com/workspaces/1/instagram/videos/{uuid}.mp4` |

- `{workspace_id}` 由已登入的後端 workspace 決定，前端不能自行指定。
- `{uuid}` 每次上傳都會新產生，避免檔名衝突或覆蓋舊素材。
- 原始使用者檔名不會成為公開 URL 的一部分。

## R2 與自有網域

R2 素材使用自有網域底下的**獨立子網域**：

```text
https://media.dynamic-adaptive-ai-agent-workflow.fengyenchen.com
```

## 驗收順序

1. 在「Instagram 內容提案」選擇一張圖片或影片上傳。
2. 確認網址自動寫入素材欄位，並可在貼文預覽中載入。
3. 用無痕視窗直接開啟素材網址。
4. 送交人工審核，確認公開素材檢查通過。

## 已知限制與後續建議

- 本次不包含 AI 生圖／影片；日後若新增，生成檔也應先上傳 R2，再回填同樣的公開網址流程。
- 未儲存的暫存素材預設會在 24 小時後由每日清理工作刪除；已保存素材會標記為引用中，不會被清理。
- 素材由瀏覽器直傳 R2，不會經過 Vercel 函式，因此大檔不受 Vercel HTTP 請求大小限制；實際上限由 `R2_MAX_UPLOAD_BYTES` 控制。
