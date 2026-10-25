# Agent Core 交接說明

## 交接範圍

本階段由林芸萱完成 Agent Core 的本機原型。接手者可在 `agent_lab/` 獨立安裝依賴、執行模型流程及離線測試；不需要改動既有 `backend` 才能重現本階段成果。

## 已驗證成果

目前流程為：

```text
使用者問題 → Gemini Agent → get_form_summary() → Agent 產生草稿
→ LangGraph 暫停等待人工審核 → 核准／修改／拒絕 → 恢復並回報結果
```

- 真實 Gemini 執行已成功呼叫 `get_form_summary()`，取回 30 人的虛構活動摘要並生成 Instagram 宣傳建議。
- 真實執行中輸入 `a` 後，流程恢復並回報 `approved`。
- 離線測試使用模擬模型，不呼叫供應商 API；涵蓋工具資料傳遞、審核修改後恢復與拒絕。
- 模型金鑰透過終端機 `getpass` 輸入，不應寫入程式碼、文件或 Git。

## 本機安裝與操作

以下指令從 repository 根目錄執行。Python 3.11 已在原開發環境驗證。

macOS／Linux：

```bash
python3 --version
python3 -m venv agent_lab/.venv
agent_lab/.venv/bin/python -m pip install -r agent_lab/requirements.txt
agent_lab/.venv/bin/python -m unittest discover -s agent_lab -p 'test_graph.py' -v
agent_lab/.venv/bin/python agent_lab/main.py
```

Windows PowerShell（在 repository 根目錄）：

```powershell
py -3.11 -m venv agent_lab\.venv
agent_lab\.venv\Scripts\python.exe -m pip install -r agent_lab\requirements.txt
agent_lab\.venv\Scripts\python.exe -m unittest discover -s agent_lab -p "test_graph.py" -v
agent_lab\.venv\Scripts\python.exe agent_lab\main.py
```

前三行安裝並執行離線測試；最後一行才會呼叫真實 Gemini。預期兩個測試皆 `ok`，最後顯示 `OK`。離線測試不需要 API key。

使用者需自行準備可用的 Google AI Studio API key；程式提示時在終端機輸入。輸入不會顯示字元。草稿出現後可輸入 `a` 核准、`e` 修改後核准或 `r` 拒絕；修改時輸入完整新草稿，空白行結束。這會呼叫 Gemini API，可能受帳戶方案與用量限制。

## 程式導覽

- `main.py`：模型設定、`get_form_summary()`、`AgentState`、LangGraph 節點與終端機審核入口。
- `test_graph.py`：離線驗證流程及 interrupt 暫停／恢復。
- `requirements.txt`：Agent Core 自己的 Python 依賴；不要以 `pip freeze` 覆蓋 `backend/requirements.txt`。
- `.venv/` 和 API key 不應加入 Git。根目錄 `.gitignore` 已忽略虛擬環境與 `agent_lab/.env`；目前程式直接提示輸入金鑰，無需建立 `.env`。

## 已知限制

1. `get_form_summary()` 回傳程式內寫死的虛構摘要；真實表單 OAuth 尚未實作。
2. `InMemorySaver` 只在同一程序期間保存狀態。關閉或重啟程式後，待審流程無法恢復。
3. 審核狀態與草稿尚未寫入 Neon；目前命令列審核通過不代表後端資料庫有記錄。
4. 目前沒有外部副作用：不會發布 Instagram、不會修改表單、不會自動執行其他工作。
5. OpenAI connector 雖列在依賴中，但目前主流程的已驗證模型是 Gemini；OpenAI 未驗證。

## 下一位負責人的起點

先閱讀根目錄的系統架構規格書，並確認團隊採用的 API、Execution、審核與 worker 契約。現有 `backend/app/main.py` 的 `POST /strategies/{strategy_id}/executions` 目前只建立 `QUEUED` Execution 記錄，尚未啟動 LangGraph。架構文件規劃的方向是：FastAPI 建立持久化工作、獨立 worker 執行 LangGraph、Neon 保存業務資料與 job、持久化 checkpointer 保存可恢復的圖狀態。

建議接手順序：

1. 先確認現有 backend schema／migration 和根目錄架構規格一致，列出缺少的 job、approval 與 checkpoint 儲存介面。
2. 定義 Agent 服務介面：輸入只收 workspace／execution 識別與必要業務資料；模型供應商金鑰只由後端環境設定提供。
3. 以虛構資料建立 worker 到 LangGraph 的整合測試，先不接 OAuth 或 Instagram 發布。
4. 再將持久化 job、approval record 和 PostgreSQL checkpointer 接入 Neon，測試程序重啟後可恢復待審流程。
5. 經團隊審查後，才逐步接真實資料來源及部署。

Agent 狀態中的 `interrupt` 僅負責流程暫停／恢復，不能取代後端的使用者身分、workspace 權限、審核紀錄或執行授權。核准後仍須由後端重新檢查審核紀錄與草稿版本。

## Git 交接

把本文件列出的 Agent Core 變更提交並推送後，隊友在自己的 clone 執行 `git pull origin main`，再依「本機安裝與操作」建立自己的虛擬環境。API key 不會隨 Git 傳遞；每位需要跑真實模型的人都要透過核准的團隊流程取得自己的 key。不要把 key 貼在聊天、commit、issue 或程式檔。

接手者可用 `git log -1 --oneline` 確認目前版本，並先跑離線測試；測試通過後再自行決定是否使用自己的 API key 執行 Gemini。
