# 策略成效評估與下一輪建議

2026-11-09 · 第四份工作交接 · `dengdee`

## 完成內容

評估單位是某個策略版本的單次執行。API 依 `Execution.strategy_id → Strategy.goal_id → Goal.kpi_definition` 找到目標，再從同一 workspace、策略及執行的 `Observation` 取得實績。`ExternalEvent` 保存原始來源，`Observation` 每列保存一個指標。

| 位置 | 改動 |
|---|---|
| `frontend/app/dashboard.tsx` | 新增工作時可填觸及與有效報名的數量目標。選填，留白的項目不列入評估。 |
| `backend/app/evaluation.py` | LangGraph 先執行 `evaluation` 計算 KPI，再執行 `recommend_next_strategy` 產生下一輪建議。 |
| `backend/app/main.py` | 新增執行評估的 GET 與 POST。 |
| `backend/app/models.py`、`backend/app/schemas.py`、migration `0010` | 在 `executions` 新增可空的 JSON 欄位 `evaluation_result`，保存最新評估快照。 |
| `backend/tests/test_evaluation.py`、`backend/tests/test_platform.py` | 新增結果重播與模擬 LLM 測試，更新 migration 版本斷言。 |

## KPI 選擇與判定

| KPI | 計算口徑 | 用途 |
|---|---|---|
| `reach` 觸及帳號數 | 取指定執行的最新有效來源快照。累計觸及應由來源按帳號去重。 | 衡量曝光是否達標。 |
| `registrations` 有效報名人數 | 取指定執行的最新來源快照。匯入端需先依活動約定的有效條件篩選並去重。 | 衡量招募目標是否達成。活動總報名與可歸因於貼文的報名應採各自一致的口徑。 |

連結點擊目前無法取得，已自表單、評估與 Neon 測試事件移除。每項比較輸出目標、實績、差值（實績減目標）、達標狀態、觀測時間、來源事件與歸因狀態。分析時可另外計算達成率（實績 ÷ 正數目標），目前 API 直接回傳差值。

- `SUCCESS` 表示所有已設定的支援 KPI 都達標。
- `PARTIAL_SUCCESS` 表示有達標也有未達標。
- `FAILURE` 表示已設定的支援 KPI 全部未達標。
- `UNABLE_TO_EVALUATE` 表示沒有支援的數值目標，或有目標／觀測資料缺漏或無效。

每項以實績大於等於目標為達標，數值門檻與分級規則由專案事先設定。既有 `kpi_definition={}` 的 Goal 需要補明確目標。百分比成長目標需要基準值，現行流程支援絕對數量目標。

## 論文依據

- Beichert、Bayerl、Goldenberg 與 Lanz（2024），*Journal of Marketing*。研究分開衡量觸及、互動及最終營收。本專案借用分階段衡量的做法，以有效報名作為社團活動的最終行動指標。 [Revenue Generation Through Influencer Marketing](https://journals.sagepub.com/doi/10.1177/00222429231217471)
- Li 與 Kannan（2014），*Journal of Marketing Research*。研究多渠道接觸與轉換歸因，可用來說明活動總報名與貼文可歸因報名為何需要分開。 [Attributing Conversions in a Multichannel Online Marketing Environment](https://journals.sagepub.com/doi/10.1509/jmr.13.0050)
- Gordon、Moakler 與 Zettelmeyer（2023 卷期），*Marketing Science*。以 663 個 Facebook 廣告實驗檢驗非實驗估計方法。用於界定本專案的結論為觀測到的實績與達標情形。若要估計策略額外帶來的報名，需能識別增量效果的研究設計。 [Close Enough? A Large-Scale Exploration of Non-Experimental Approaches to Advertising Measurement](https://pubsonline.informs.org/doi/10.1287/mksc.2022.1413)

## 重播與驗證

Neon `public` 已套用 migration `0010`。測試資料關聯為 Goal #2、Strategy #4（v1）、Execution #13、ExternalEvent #20。來源標為 `synthetic`，報名歸因狀態為 `unattributed`。

| KPI | 目標 | 虛擬實績 | 差值 |
|---|---:|---:|---:|
| 觸及帳號數 | 3,000 | 3,600 | +600 |
| 有效報名人數 | 40 | 28 | −12 |

預期為 `PARTIAL_SUCCESS`。建議可沿用曝光做法，優先測試一項報名流程變因，並在下一輪記錄來源。這組結果描述的是模擬活動總報名。

在 FastAPI 的 `/docs` 用開發 API key 授權後，可用以下端點重播。評估端點無須 request body。

| 操作 | 端點 |
|---|---|
| 即時試算 | `GET /executions/13/evaluation` |
| 計算並保存最新快照 | `POST /executions/13/evaluation` |
| 讀取保存結果 | `GET /executions/13`，查看 `evaluation_result` |

從 `backend/` 執行 `python -B -m unittest tests.test_evaluation tests.test_agent_runner -v`。最近一次 11 項通過，涵蓋三種結果、缺資料與模擬 LLM 回覆。此前也已通過前端 TypeScript 檢查。Neon 已讀回 Execution #13 的保存快照。加入 `recommendation_source` 後，可用 POST 重算以更新舊快照。

## LLM 與憑證

在本機 `backend/.env` 設定 `AGENT_PROVIDER`、`AGENT_MODEL` 及對應金鑰。Gemini 使用 `GOOGLE_API_KEY`，OpenAI 使用 `OPENAI_API_KEY`，Claude 使用 `ANTHROPIC_API_KEY`。設定同時供既有策略 Agent 使用，修改後重啟 FastAPI。Neon runtime 使用 `DATABASE_URL`，migration 使用 `MIGRATION_DATABASE_URL`，Swagger 授權使用 `PLATFORM_API_KEY`。

模型接收原策略、Goal 標題、程式算出的 KPI 與歸因狀態，輸出繁體中文建議。`recommendation_source=llm` 表示採用模型回覆，`rules` 表示使用規則。最近一次 OpenAI 實測遇到金鑰驗證失敗並回退。Gemini 真實回覆仍待驗證。

## 限制與接手步驟

1. 使用有效的 provider 憑證重跑 Execution #13，確認 API 與保存快照出現 `recommendation_source=llm`。
2. 後續接入真實觸及與有效報名時，先約定觀測截止時間、去重及歸因。現行 API 依各指標的最新觀測評估，並保留各筆時間與來源。若要做跨版本比較，需採用一致的窗口。
3. 目前只保存最新快照與下一輪建議文字。正式建立 Strategy v2 或保留歷次評估，待後續串接。

Git 基準為 `65beedf`。本文件與實作一併提交至 `dengdee`，提交訊息為 `feat: evaluate strategy execution KPIs`。
