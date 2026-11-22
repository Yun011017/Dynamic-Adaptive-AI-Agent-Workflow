# Instagram 內容提案 Agent 編修交接

## 已完成：與 Agent 編修 Instagram 貼文

前端在內容提案工作區下方提供全寬的「與 Agent 編修貼文」區塊。使用方式如下：

1. 使用者先從「此 Strategy 的內容提案」選擇一則待編修提案。
2. 在對話框輸入修改方向，例如「開頭更吸引零基礎同學，保留原 CTA」。
3. Agent 回傳文字說明與一份完整的內容提案建議。
4. 右側「本次建議會怎麼改」以行內修訂稿顯示差異：
   - 紅色刪除線：會移除的文字。
   - 綠色文字：會新增的文字。
   - 長文與網址完整顯示，並在卡片內換行；清單可上下捲動。
5. 使用者可直接忽略建議；**未按套用不會改動任何內容**。
6. 按「套用建議，繼續修改」後，建議會帶回上方內容提案與 Instagram 預覽；使用者仍可手動改字、hashtags、素材需求。
7. 只有按既有的「建立新版本」才會保存，並走原本的人工審核／發布流程。

多輪編修以目前尚未儲存的內容提案為基準：先套用第一個修改、再提出第二個修改時，第二次 Agent 會看到第一個已套用的結果，不會退回最初版本。若已套用後反悔，右側會出現「不要這次修改，還原內容提案」，可復原最後一次套用。

Agent 不會改動素材網址、發布時間、貼文格式或報名連結；這些內容仍由原內容提案表單管理。

## 報名表單綁定流程後續處理

目前的「報名表單綁定」是先前 Google Forms／Apps Script 資料匯入流程留下的介面。之後由 Agent 生成活動報名表草稿的功能完成時：

- **應移除或以新流程取代「報名表單綁定」功能**，避免使用者以為建立表單仍需手動設定 Apps Script、人工／AI 欄位與 Execution 綁定。
- 活動報名表草稿完成後，使用者只需確認或建立表單，不應自行處理資料端點。
- 現有表單匯入、來源設定與 Execution 資料模型可暫時保留為後端相容層，但不宜繼續當作正式使用者流程。

## 後端 API 與主要檔案

新增端點：

| API | 用途 |
| --- | --- |
| `POST /content-drafts/{action_id}/assistant` | 對特定內容提案提出編修建議；不儲存、不發布。 |

請求包含 `message` 與可選的 `current_content`。前端每次帶入目前表單內容，因此可以累積多輪未儲存修改。回應包含 `reply` 與完整 `suggestion`（title、caption、hashtags、圖片／影片素材需求）。

主要檔案：

- `backend/app/content_generator.py`：`revise_content_draft_with_agent`，提供安全的結構化編修建議。
- `backend/app/schemas.py`：Agent 編修請求／回應的資料驗證。
- `backend/app/main.py`：編修 API、模型失敗日誌與可讀錯誤。
- `backend/tests/test_content_generator.py`：編修建議結構測試。
- `frontend/app/dashboard.tsx`：對話、行內差異、套用與還原操作。

## 驗證結果

已完成：

- `python -m unittest tests.test_content_generator`
- `python -m compileall -q app`
- `npx tsc --noEmit --pretty false`
- `git diff --check`
- 已提交並推送 Agent 編修功能至 `main`：`fcbb52b feat: add agent content draft editing`。
- 已在可連線 Gemini 的環境完成瀏覽器端多輪編修驗收。
- 已實測「套用第一輪 → 第二輪繼續修改 → 建立新版本 → 人工審核」完整流程成功。
- 前端與後端 Vercel 已部署最新版：前端包含 `8ed8f41`，其父提交 `fcbb52b` 含 Agent 編修功能；後端健康頁與 Agent 編修 API 路徑皆正常。

尚待：

- 本次 Agent 編修功能的驗收已完成；其他後續工作（表單綁定流程淘汰、表單草稿與成效整合）請見下一節。

## 下一位可直接開始的工作

1. 在有網路的環境測試 Agent 編修，確認模型回覆能產生結構化建議。
2. 完成 Agent 生成活動報名表草稿後，移除／替換目前的「報名表單綁定」流程。
3. 將表單建立、來源辨識、欄位對照與同步改為系統內流程，也不要要求每次手動建立 Apps Script 資料端點。
4. 若保留成效歸因，應由每個內容提案／Execution 自動產生可辨識的來源或追蹤連結，而不是讓填表者自行選擇文案來源。
5. 在發布紀錄或對應內容提案加入「報名成效與評估」摘要：已同步回覆數、有效報名數、最後同步時間、來源與同步狀態；只呈現彙總，不顯示姓名或 Email。
