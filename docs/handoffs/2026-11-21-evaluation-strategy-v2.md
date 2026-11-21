# 評估結果自動建立下一版策略交接

## 完成內容

完成「Execution 評估 → 下一輪策略建議 → Agent 背景工作 → 新 Strategy 版本」流程。評估資料不足時只保存評估結果，不會建立策略工作。

- `POST /executions/{execution_id}/evaluation` 計算並保存評估結果；若有足夠 KPI 資料，會同一交易建立 `EVALUATION_FOLLOWUP` AgentRun。
- 工作 Context 包含來源 Execution、原 Strategy ID／版本／內容、KPI 結果與建議。
- 一般重複 POST 回傳已保存快照與同一 AgentRun，避免重複建立策略。
- `POST /agent/runs/{run_id}/retry` 僅重新排入目前評估所關聯、狀態為 FAILED 的 follow-up 工作。
- `POST /executions/{execution_id}/evaluation?refresh=true` 明確重算評估。若前一工作仍為 PENDING 或 RUNNING，回傳 409；若工作已結束，建立新的評估結果與後續工作。
- Worker 沿用 Goal 下的版本遞增邏輯建立 Strategy，並在策略內容記錄來源 Execution、來源 Strategy 與 AgentRun。
- Local Agent 會明確將上一輪評估建議納入策略方向；Gemini Agent 將完整評估 Context 傳給模型，並維持原有表單摘要工具呼叫要求。

## 驗證

- Evaluation、AgentRunner、AgentWorker 離線測試共 21 項通過。
- 隔離 PostgreSQL 測試驗證有效評估、重複提交、執行中禁止重算、失敗工作重試、Strategy v2 版本與來源欄位，以及工作完成後重新評估。
- 使用設定好的 Gemini 金鑰完成真實模型驗證：評估建議標記為 `recommendation_source=llm`，建議進入 follow-up context，Gemini 產生內容並成功保存 Strategy v2。測試只使用隔離資料庫與虛擬活動觀測值。
- 安裝本機 `backend/requirements-dev.txt` 時補齊 `boto3`，使 Worker 測試可載入 R2 服務模組。

## 操作方式

1. `POST /executions/{id}/evaluation`：建立／取得評估快照與下一輪 AgentRun。
2. 以回應中的 `next_strategy_run_id` 查詢 `GET /agent/runs/{run_id}`，等待狀態完成並查看 `output_payload.strategy_id` 與 `strategy_version`。
3. 若工作失敗，呼叫 `POST /agent/runs/{run_id}/retry`。
4. 若要使用新觀測資料重新計算，呼叫 `POST /executions/{id}/evaluation?refresh=true`；等待中或執行中的 follow-up 需先完成。

## 限制

- 評估快照仍保存於 Execution 的 `evaluation_result` 欄位；重新評估會更新最新快照，不保留完整歷史快照。
- 完整 Gemini 整合驗證採用虛擬活動資料，正式活動資料與平台成效匯入仍須各自驗收。
- 本次實作尚未部署。
