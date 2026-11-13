# Goal 與 Strategy v1 交接說明

## 本次完成

已使用 Instagram 工作坊資料建立第一個活動目標，並完成一次 Agent 策略產生流程：

```text
建立 Goal
→ Agent Run
→ Agent 分析完成
→ 建立 Strategy v1
```

目前資料：

- Goal ID：`20`
- Goal：提升 Instagram 工作坊觸及與報名
- 觸及目標：`600`
- 有效報名目標：`14`
- Agent Run：`50`，狀態為 `COMPLETED`
- Strategy ID：`25`，版本為 `v1`

## 驗證方式

已在 Neon SQL Editor 確認三筆資料：

1. Goal 已建立並包含 KPI 目標。
2. Agent Run 已完成。
3. Strategy v1 已建立並關聯 Goal ID `20`。

## 注意事項

- `AgentRun.output_payload` 是執行快照；後續流程應引用 `strategies` 的正式資料。
- 目前確認的是資料流程與 Strategy v1 建立成功；完整內容呈現可由前端 Strategy 詳情頁補上。
- 不要把 Neon 密碼、API key 或 OAuth token 寫入交接文件或提交 Git。

## 下一步

- 將 Strategy v1 的內容在前端清楚呈現。
- 以 `strategy_id` 建立內容提案。
- 接續排程、人工審核與 Instagram 發布流程。
- 發布後寫入成效資料，供下一輪策略評估。

## 對應程式狀態

本次以目前已完成的 Agent Strategy 流程與 Neon 資料為基礎，未新增程式碼或 migration。
