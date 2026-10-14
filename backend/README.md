# 後端

使用 FastAPI、SQLAlchemy 與 psycopg，連接 Neon PostgreSQL。

## 目錄

- `app/main.py`：API 入口與健康檢查。
- `app/config.py`：讀取 `backend/.env` 的資料庫設定，不受啟動所在目錄影響。
- `.env.example`：後端環境設定範本。
- `.env`：本機後端環境設定，不納入 Git。
- `app/db.py`：資料庫引擎與 Session。
- `app/models.py`：Goal、Strategy 與 Execution 資料模型。
- `requirements.txt`：Python 套件依賴。

目前已建立後端骨架；業務 API、AI Agent 與外部平台整合尚未實作。

完整環境設定與 Windows CMD 啟動步驟見 [專案說明](../README.md#啟動方式)。
請從專案根目錄執行啟動指令。
