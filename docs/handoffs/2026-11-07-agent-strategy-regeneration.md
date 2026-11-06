# Agent Strategy 讀取、版本與內容草稿交接

## 一、交接範圍

本次完成 Agent 從 Neon 讀取既有資料、產生正式 Strategy、重新產生 Strategy 版本，以及讓不同 Strategy 版本的內容草稿保持正確關聯。

## 二、已完成流程

完整流程如下：

```text
建立 Goal
→ POST /agent/runs（必須帶 goal_id）
→ worker 讀取 form_responses、ExternalEvent、Observation
→ LangGraph StateGraph 放入 RunState
→ 產生 recommendation / Strategy
→ 寫入 strategies
→ 回寫 AgentRun.output_payload
→ 以 strategy_id 建立內容草稿工作
→ 建立 Execution / ExecutionAction
```

同一個活動重新產生時：

```text
沿用同一 goal_id
→ 建立新的 AgentRun
→ Strategy version = 目前最大版本 + 1
→ 舊 Strategy 保留
→ 新內容草稿只關聯新版 strategy_id
```

## 三、資料契約

### 建立 Agent Run

`POST /agent/runs` 必須提供既有的 `goal_id`：

```json
{
  "goal_id": 3,
  "goal": "Improve workshop registrations",
  "context": "Student club event",
  "constraints": {
    "channel": "instagram"
  }
}
```

### AgentRun.output_payload

成功後至少包含：

```json
{
  "strategy_id": 12,
  "goal_id": 3,
  "strategy_version": 1,
  "strategy": {
    "target_audience": "偏好實作內容的學生",
    "content_direction": "強調實際作品與體驗流程",
    "channel": "instagram",
    "expected_metrics": ["reach", "clicks", "registrations"],
    "reason": "根據表單回覆與既有觀測資料分析"
  },
  "data_source": {
    "form_response_ids": [],
    "observation_ids": [],
    "external_event_ids": []
  }
}
```

`AgentRun.output_payload` 是執行快照與除錯紀錄；`strategies` 是後續內容草稿、排程與成效觀測引用的正式資料來源。

## 四、版本規則

- 第一次產生為 Strategy v1。
- 同一 `workspace_id + goal_id` 重新產生時建立 v2、v3……。
- 舊 Strategy 不覆寫。
- Strategy 版本由 worker 取得目前最大版本後加一，並鎖定 Goal 避免同時產生時重複版本。
- v1 的內容草稿繼續關聯 v1 的 `strategy_id`。
- v2 會建立新的內容草稿，不會把舊內容改連到 v2。

## 五、主要修改位置

- `backend/app/agent_runner.py`：RunState、LangGraph 輸入與 recommendation。
- `backend/app/agent_worker.py`：讀取 Neon、建立 Strategy、版本遞增、內容草稿串接。
- `backend/app/main.py`：`POST /agent/runs` 驗證並保存 `goal_id`。
- `backend/app/models.py`：`AgentRun.goal_id` 與 workspace/goal 複合外鍵。
- `backend/app/schemas.py`：Agent Run request/response 契約。
- `backend/migrations/versions/0009_agent_run_goal.py`：新增 `agent_runs.goal_id`。
- `frontend/app/dashboard.tsx`：重新產生 Strategy 按鈕，沿用原 Goal 的資料。

## 六、驗證結果

在隔離 PostgreSQL schema 執行：

```bash
cd backend
../.venv/bin/python -m unittest tests.test_platform tests.test_agent_worker tests.test_agent_runner -v
```

結果：34/34 通過。

另外已確認：

- Neon migration 版本為 `0009`。
- `agent_runs.goal_id` 已存在。
- 前端 `npx tsc --noEmit` 通過。
- 前端 `CI=1 npm run build` 成功。
- `git diff --check` 通過。
- 未追蹤 `.env` 或金鑰檔案。

## 七、環境設定

- Agent 目前使用 `AGENT_PROVIDER=local` 與 `AGENT_MODEL=deterministic-langgraph` 做可重現驗證。
- 真實模型 Provider 的金鑰只放在本機或部署環境的 `.env`，不可提交 Git。
- Neon migration 使用 `MIGRATION_DATABASE_URL`；runtime 使用 `DATABASE_URL`。
- 交接時不在文件或訊息中複製資料庫密碼、API key、OAuth token。

## 八、已知限制與下一步

- 相同輸入在 local provider 下可能產生相同文字內容；版本與資料關聯仍然不同。
- `next lint` 會因專案沒有 ESLint 設定而進入互動式設定；production build 的 lint/type 檢查已通過。
- npm 安裝時回報目前 Next.js 版本有相依性安全漏洞；升級需另行確認相容性，不在本次交接中強制處理。
- 下一階段可接真實模型 Provider、Instagram 成效寫入 Observation，以及成效評估後的下一輪策略。

## 九、Git 交接

- 分支：`codex/sync-neon-0008`
- 基礎遠端分支：`origin/feature/approval-publishing-workflow`
- 對應 commit：`feat: complete versioned agent strategy workflow`；以本分支最新 Git commit 為準。
- 推送後請建立 Pull Request，讓團隊先檢查 migration、Agent worker 與前端流程。
