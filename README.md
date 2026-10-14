# Dynamic Adaptive AI Agent Workflow

以多渠道行銷為驗證情境的自適應 AI Agent 工作流程原型。

## 目前基礎架構

- FastAPI：後端 API
- PostgreSQL：保存 Goal、Strategy、Execution 與版本紀錄
- Docker Compose：本機一鍵啟動 API 與資料庫

## 啟動方式

1. 複製環境設定：`cp .env.example .env`
2. 啟動服務：`docker compose up --build`
3. 開啟 API 文件：<http://localhost:8000/docs>
4. 檢查服務：<http://localhost:8000/health>

## 資料模型

目前先建立持續改善循環的核心資料：

`Goal → Strategy(version) → Execution → Result`

下一步會加入 API endpoints、資料庫 migration、Agent orchestration、人工確認節點與測試資料。

