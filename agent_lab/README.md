# Agent Core 練習區

這是 NTU Challengers 專案中的獨立練習區，用來建立 LangChain／LangGraph Agent。此目錄的 Python 依賴和設定與既有 `backend` 分開管理。接手與操作步驟請先看 [`HANDOFF.md`](HANDOFF.md)。

## 已完成

- 使用 Gemini `gemini-3.5-flash-lite` 完成真實模型呼叫。
- 已配置 Gemini、OpenAI、Claude 三種 LangChain provider，預設 Gemini；目前只有 Gemini 做過真實 API 驗證。
- LangChain 模型透過 `bind_tools` 使用 `get_form_summary()`，成功取得虛構活動報名摘要並生成行銷建議。
- LangGraph 定義 `AgentState`，管理 Agent、工具與人工審核節點。
- 人工審核支援核准、修改後核准、拒絕；以 `interrupt()` 暫停並以 `Command(resume=...)` 恢復。
- 離線測試涵蓋工具流程、state 訊息、人工修改後恢復與拒絕流程。

## 重要限制與下一階段

- 測試工具回傳的是虛構資料，尚未串接 Google Forms 或其他真實資料源。
- `InMemorySaver` 只把 checkpoint 保存在執行中的程序記憶體；程序結束後不能恢復待審工作。
- 切換模型可設定 `MODEL_PROVIDER=gemini`、`MODEL_PROVIDER=openai` 或 `MODEL_PROVIDER=claude`；OpenAI 與 Claude 需要各自的 API key，可能產生費用。
- 審核目前透過命令列互動；核准只代表草稿核准，並不會發布到 Instagram。
- FastAPI／Neon 尚未呼叫 Agent。現有後端的 Execution API 只建立 `QUEUED` 記錄，沒有 Agent worker。
- 接手方向：依根目錄系統架構規格，先規劃持久化 job、LangGraph PostgreSQL checkpointer 與 worker 的責任及資料流，再接真實資料。不要將長時間 Agent 執行放在同步 HTTP request 中。
