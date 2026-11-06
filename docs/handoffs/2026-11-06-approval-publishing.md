
# 人工審核與執行發布交接

## 一、完成範圍

1. **Approval 狀態機與防護**：
   - 建立 `approval_requests` 資料表，綁定 `workspace_id`、`action_id`、`draft_version`、`content_hash`。
   - 狀態流轉支援 `PENDING_REVIEW`、`APPROVED`、`REJECTED`，並支援退回修改（退回後 Action 設為 `SUPERSEDED`）。
   - 發布前置檢查：未核准強制阻擋 (403)、雜湊不符防竄改 (409)、SUPERSEDED 防舊版外呼 (409)、OAuth 授權有效性。
2. **Meta 受控發布**：
   - 實作單張圖片與輪播（先建立 child containers 再建立 parent container）兩階段發布。
   - 實作 Container `status_code == FINISHED` 輪詢等待機制。
   - 發布成功回寫 `external_id` 並改為 `SUCCEEDED`；失敗改為 `FAILED`。
3. **前端 Console**：
   - Dashboard 整合「送交人工審核」、「待審核貼文佇列」（可核准/退回/拒絕）與「核准通過：立即發布到 IG」按鈕。

## 二、「排程發布」與「版本修訂 (Revision)」流程邊界與限制

1. **排程與審核的關係**：
   - 「已排程 (SCHEDULED)」不等於「已核准 (APPROVED)」。
   - 排程設定只代表時間已規劃。草稿必須經過「送審 → APPROVED」後，Worker 才能在排程時間到達時執行發布。
2. **修訂建立新版本的衝突規避**：
   - 當 Action 已獲得核准 (APPROVED) 或已排程 (SCHEDULED)，一旦使用者點擊「建立新版本」，原 Action 會立即被標示為 `SUPERSEDED`。
   - **不變條件**：`SUPERSEDED` 的舊 Action 嚴禁被發布；舊版本的 Approval 不得繼承給新版本。
   - **後續建議**：
     - 若使用者只想修改排程時間（不變更文案與圖片），可新增「單純變更排程時間」之獨立端點，避免重新計算 `content_hash` 與產生新版本。
     - 若文案或圖片被修改產生新版本，介面應明確提示「已產生新版本，需重新送審核准後排程才生效」。
