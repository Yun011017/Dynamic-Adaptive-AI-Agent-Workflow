import os
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import httpx
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")

APP_ID = os.getenv("META_APP_ID")
APP_SECRET = os.getenv("META_APP_SECRET")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")
API_VER = os.getenv("GRAPH_API_VERSION", "v21.0")

# 用於加密底層 Token 的密鑰（實務上可存於環境變數）
ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
cipher = Fernet(ENCRYPTION_KEY.encode())

# 我們在第一步整理的 Facebook Login 必備 Scopes
SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
    "business_management", # 避免部分新版粉專綁定在 Business Portfolio 下查不到
]

app = FastAPI(title="IG Integration Sandbox")
STATE_STORE = set()
DB_PATH = str(PROJECT_DIR / "sandbox.db")


import json

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                ig_user_id TEXT UNIQUE NOT NULL,
                ig_username TEXT,
                page_id TEXT NOT NULL,
                scopes TEXT NOT NULL,
                status TEXT NOT NULL,
                encrypted_token TEXT NOT NULL,
                expires_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        # 儲存從 IG 讀取回來的外部事件與觀測資料 (external event / observation)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS external_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ig_user_id TEXT NOT NULL,
                observation_type TEXT NOT NULL, -- 'account_profile' | 'media_post' | 'media_insights'
                external_id TEXT NOT NULL,      -- IG user id 或 media id
                payload_json TEXT NOT NULL,     -- 觀測內容 JSON
                observed_at TEXT NOT NULL
            )
        """)
        # 記錄 Meta API 呼叫狀態、錯誤碼與 retryable 判斷
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                http_status INTEGER NOT NULL,
                meta_error_code INTEGER,
                meta_error_subcode INTEGER,
                error_message TEXT,
                retryable INTEGER NOT NULL,     -- 1 (True) | 0 (False)
                called_at TEXT NOT NULL
            )
        """)
        # 儲存待發布的貼文草稿 (Draft)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS post_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ig_user_id TEXT NOT NULL,
                image_url TEXT NOT NULL,
                caption TEXT NOT NULL,
                status TEXT NOT NULL, -- 'draft' | 'pending_approval' | 'approved' | 'published' | 'failed'
                published_media_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # 儲存審核請求紀錄 (Approval Request)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id INTEGER UNIQUE NOT NULL,
                status TEXT NOT NULL, -- 'pending' | 'approved' | 'rejected'
                reviewer TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(draft_id) REFERENCES post_drafts(id)
            )
        """)


init_db()


@app.get("/auth/login")
def login():
    """步驟 1：使用 Facebook Login for Business 的 config_id 發起授權"""
    state = secrets.token_urlsafe(16)
    STATE_STORE.add(state)
    config_id = os.getenv("META_CONFIG_ID")
    
    params = {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "response_type": "code",
    }
    if config_id:
        params["config_id"] = config_id
    else:
        params["scope"] = ",".join(SCOPES)

    auth_url = f"https://www.facebook.com/{API_VER}/dialog/oauth?{urlencode(params)}"
    return RedirectResponse(auth_url)   


@app.get("/auth/callback")
async def oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
):
    """步驟 2：處理 OAuth Callback、換取長效 Token、反查 IG Professional Account 並寫入 oauth_connections"""
    if error:
        raise HTTPException(status_code=400, detail={"error": error, "description": error_description})
    if not state or state not in STATE_STORE:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    STATE_STORE.remove(state)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. 用 code 換取短期 User Access Token
        token_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}/oauth/access_token",
            params={
                "client_id": APP_ID,
                "redirect_uri": REDIRECT_URI,
                "client_secret": APP_SECRET,
                "code": code,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=token_resp.status_code, detail=token_resp.json())
        short_token = token_resp.json()["access_token"]

        # 2. 換取 60 天長效權杖 (Long-Lived Token)
        ll_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": APP_ID,
                "client_secret": APP_SECRET,
                "fb_exchange_token": short_token,
            },
        )
        ll_data = ll_resp.json()
        access_token = ll_data.get("access_token", short_token)
        expires_in = ll_data.get("expires_in", 5184000) # 預設 60 天
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

       # 3. 找出綁定的 Instagram Professional Account（支援 /me/accounts + /me/businesses + 備援直連）
        pages_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}/me/accounts",
            params={
                "fields": "id,name,instagram_business_account{id,username,account_type},connected_instagram_account{id,username}",
                "access_token": access_token,
            },
        )
        pages_data = pages_resp.json().get("data", [])

        # 若 /me/accounts 為空，從 /me/businesses 搜出所有商家組合下的粉專與直連 IG 帳號
        biz_ig_accounts = []
        if not pages_data:
            biz_resp = await client.get(
                f"https://graph.facebook.com/{API_VER}/me/businesses",
                params={
                    "fields": (
                        "id,name,"
                        "owned_pages{id,name,instagram_business_account{id,username},connected_instagram_account{id,username}},"
                        "client_pages{id,name,instagram_business_account{id,username},connected_instagram_account{id,username}},"
                        "instagram_business_accounts{id,username},"
                        "owned_instagram_accounts{id,username}"
                    ),
                    "access_token": access_token,
                },
            )
            for biz in biz_resp.json().get("data", []):
                pages_data.extend(biz.get("owned_pages", {}).get("data", []))
                pages_data.extend(biz.get("client_pages", {}).get("data", []))
                biz_ig_accounts.extend(biz.get("instagram_business_accounts", {}).get("data", []))
                biz_ig_accounts.extend(biz.get("owned_instagram_accounts", {}).get("data", []))

        ig_account = None
        target_page_id = os.getenv("FALLBACK_PAGE_ID", "business_portfolio_direct")

        for page in pages_data:
            ig_obj = page.get("instagram_business_account") or page.get("connected_instagram_account")
            if ig_obj:
                ig_account = ig_obj
                target_page_id = page["id"]
                break

        # 若粉專沒展開 IG，直接採用從 Business Portfolio 抓到的 IG Professional Account
        if not ig_account and biz_ig_accounts:
            ig_account = biz_ig_accounts[0]

        # 若備援環境變數有設定 FALLBACK_IG_USER_ID 或 FALLBACK_PAGE_ID，直接用 Token 驗證讀取
        if not ig_account and os.getenv("FALLBACK_IG_USER_ID"):
            fb_ig_id = os.getenv("FALLBACK_IG_USER_ID")
            ig_resp = await client.get(
                f"https://graph.facebook.com/{API_VER}/{fb_ig_id}",
                params={"fields": "id,username", "access_token": access_token},
            )
            if ig_resp.status_code == 200 and "id" in ig_resp.json():
                ig_account = ig_resp.json()

        if not ig_account:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "找不到綁定的 Instagram Professional Account！請確認在 business.facebook.com/settings 已將人員指派給粉專與 IG。",
                    "businesses_raw": biz_resp.json() if "biz_resp" in locals() else None,
                    "pages_found": pages_data,
                },
            )

        
        # 4. 加密 Token 並寫入 oauth_connections# 動態取得此 Token 實際被授予的權限清單
        perm_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}/me/permissions",
            params={"access_token": access_token},
        )
        granted_permissions = [
            p["permission"]
            for p in perm_resp.json().get("data", [])
            if p.get("status") == "granted"
        ]

        # 加密 Token 並寫入 oauth_connections
        encrypted_token = cipher.encrypt(access_token.encode()).decode()
        now_iso = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO oauth_connections (
                    provider, ig_user_id, ig_username, page_id, scopes, status, encrypted_token, expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ig_user_id) DO UPDATE SET
                    ig_username=excluded.ig_username,
                    page_id=excluded.page_id,
                    scopes=excluded.scopes,
                    status='authorized',
                    encrypted_token=excluded.encrypted_token,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                """,
                (
                    "meta_instagram",
                    ig_account["id"],
                    ig_account.get("username"),
                    target_page_id,
                    ",".join(granted_permissions),  # 動態寫入實際生效的權限
                    "authorized",
                    encrypted_token,
                    expires_at,
                    now_iso,
                ),
            )

    return {
        "message": "OAuth flow 成功！",
        "connection": {
            "provider": "meta_instagram",
            "ig_user_id": ig_account["id"],
            "ig_username": ig_account.get("username"),
            "page_id": target_page_id,
            "status": "authorized",
            "scopes": granted_permissions,  # 回傳真實生效的 Scopes
            "expires_at": expires_at,
        },
    }       

@app.get("/connections")
def list_connections():
    """檢視 oauth_connections 狀態（驗證：有授權狀態，但絕不查詢或暴露 token 欄位）"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, provider, ig_user_id, ig_username, page_id, scopes, status, expires_at, updated_at FROM oauth_connections"
        ).fetchall()
    return {"oauth_connections": [dict(r) for r in rows]}
def classify_meta_error(http_status: int, resp_json: dict) -> dict:
    """
    解析 Meta Graph API 回應，判斷是否為錯誤以及是否可重試 (retryable)：
    - Retryable (True): HTTP 5xx, 429, 或 Meta Error Code 1, 2 (暫時性錯誤), 4, 17, 32, 613 (Rate Limit)
    - Non-retryable (False): Code 190 (Token 過期/撤銷), Code 10/200 (權限不足), Code 100 (參數無效)
    """
    err = resp_json.get("error") if isinstance(resp_json, dict) else None
    if http_status == 200 and not err:
        return {"is_error": False, "code": None, "subcode": None, "message": None, "retryable": False}

    code = err.get("code") if err else None
    subcode = err.get("error_subcode") if err else None
    message = err.get("message", "Unknown API Error") if err else str(resp_json)
    is_transient = err.get("is_transient", False) if err else False

    retryable_codes = {1, 2, 4, 17, 32, 613}
    retryable = (
        is_transient
        or http_status in {429, 500, 502, 503, 504}
        or (code in retryable_codes)
    )
    return {
        "is_error": True,
        "code": code,
        "subcode": subcode,
        "message": message,
        "retryable": retryable,
    }


def log_api_call(endpoint: str, http_status: int, resp_json: dict) -> dict:
    """將每次 Meta API 呼叫的狀態、錯誤與 retryable 判斷寫入 api_call_logs"""
    info = classify_meta_error(http_status, resp_json)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO api_call_logs (endpoint, http_status, meta_error_code, meta_error_subcode, error_message, retryable, called_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endpoint,
                http_status,
                info["code"],
                info["subcode"],
                info["message"],
                1 if info["retryable"] else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return info


def get_active_connection():
    """從資料庫取出已授權連線並於記憶體內解密 Token（絕不對外回傳）"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM oauth_connections WHERE status = 'authorized' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="尚無有效的 OAuth 授權連線，請先執行 /auth/login")
    try:
        token = cipher.decrypt(row["encrypted_token"].encode()).decode()
    except Exception:
        raise HTTPException(status_code=401, detail="Token 解密失敗（可能因重啟變更了 TOKEN_ENCRYPTION_KEY），請重新執行一次 /auth/login")
    return dict(row), token


@app.get("/ig/sync")
async def sync_ig_observations():
    """
    步驟 3 & 4：讀取 IG 帳號與貼文資料 (Read Operation) + 儲存 external event / observation
    """
    conn_row, access_token = get_active_connection()
    ig_user_id = conn_row["ig_user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    saved_observations = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. 讀取帳號基本資料與粉絲/貼文數 (Read Profile & Basic Insights)
        profile_ep = f"/{ig_user_id}"
        profile_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}{profile_ep}",
            params={
                "fields": "id,username,name,media_count,followers_count,follows_count,biography",
                "access_token": access_token,
            },
        )
        p_json = profile_resp.json()
        p_err = log_api_call(profile_ep, profile_resp.status_code, p_json)
        if p_err["is_error"]:
            raise HTTPException(status_code=profile_resp.status_code, detail={"api_error": p_err, "raw": p_json})

        # 2. 讀取最新貼文列表與互動成效 (Read Media & Engagement Metrics)
        media_ep = f"/{ig_user_id}/media"
        media_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}{media_ep}",
            params={
                "fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
                "limit": 10,
                "access_token": access_token,
            },
        )
        m_json = media_resp.json()
        m_err = log_api_call(media_ep, media_resp.status_code, m_json)
        if m_err["is_error"]:
            raise HTTPException(status_code=media_resp.status_code, detail={"api_error": m_err, "raw": m_json})

        media_list = m_json.get("data", [])

        # 3. 將讀取結果寫入 external_observations 表
        with sqlite3.connect(DB_PATH) as conn:
            # 儲存帳號 Observation
            conn.execute(
                """
                INSERT INTO external_observations (ig_user_id, observation_type, external_id, payload_json, observed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ig_user_id, "account_profile", ig_user_id, json.dumps(p_json, ensure_ascii=False), now_iso),
            )
            saved_observations.append({"type": "account_profile", "external_id": ig_user_id})

            # 儲存每篇貼文 Observation
            for post in media_list:
                conn.execute(
                    """
                    INSERT INTO external_observations (ig_user_id, observation_type, external_id, payload_json, observed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ig_user_id, "media_post", post["id"], json.dumps(post, ensure_ascii=False), now_iso),
                )
                saved_observations.append({"type": "media_post", "external_id": post["id"]})

    return {
        "message": "Read Operation 成功，並已寫入 external_observations！",
        "account_profile": p_json,
        "media_count_fetched": len(media_list),
        "media_posts": media_list,
        "saved_observations": saved_observations,
    }


@app.get("/observations")
def list_observations():
    """檢視已儲存的 external_observations 與 API 呼叫/錯誤紀錄"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        obs = conn.execute("SELECT * FROM external_observations ORDER BY id DESC LIMIT 20").fetchall()
        logs = conn.execute("SELECT * FROM api_call_logs ORDER BY id DESC LIMIT 20").fetchall()
    return {
        "external_observations": [
            {**dict(r), "payload_json": json.loads(r["payload_json"])} for r in obs
        ],
        "api_call_logs": [dict(r) for r in logs],
    }

from pydantic import BaseModel

class DraftCreateRequest(BaseModel):
    # Meta 規定發布圖片必須是公開可存取的 HTTPS JPEG 網址
    image_url: str = "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=80"
    caption: str = "Sandbox Automated Test Post via Meta Graph API #IGSandbox"


@app.post("/posts/drafts")
def create_draft_and_approval_request(body: DraftCreateRequest = DraftCreateRequest()):
    """
    1. 建立貼文草稿 (Draft) 並自動發起審核請求 (Approval Request, 初始狀態為 pending)
    """
    conn_row, _ = get_active_connection()
    ig_user_id = conn_row["ig_user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO post_drafts (ig_user_id, image_url, caption, status, created_at, updated_at)
            VALUES (?, ?, ?, 'pending_approval', ?, ?)
            """,
            (ig_user_id, body.image_url, body.caption, now_iso, now_iso),
        )
        draft_id = cur.lastrowid

        cur_app = conn.execute(
            """
            INSERT INTO approval_requests (draft_id, status, created_at)
            VALUES (?, 'pending', ?)
            """,
            (draft_id, now_iso),
        )
        approval_id = cur_app.lastrowid

    return {
        "message": "已建立 Draft 與 Approval Request（目前狀態為 pending，直接呼叫 publish 將被拒絕）",
        "draft_id": draft_id,
        "approval_request_id": approval_id,
        "draft_status": "pending_approval",
        "approval_status": "pending",
    }


@app.post("/posts/drafts/{draft_id}/publish")
async def publish_draft(draft_id: int):
    """
    2. 執行發布操作：
       - 【核心防護】：檢查是否有對應且 status == 'approved' 的 approval_request，若無則強制拒絕 (HTTP 403)！
       - 若已核准，呼叫 Meta Graph API 兩階段發布 (建立 Container -> 執行 media_publish)
    """
    conn_row, access_token = get_active_connection()
    ig_user_id = conn_row["ig_user_id"]

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        draft = conn.execute("SELECT * FROM post_drafts WHERE id = ?", (draft_id,)).fetchone()
        if not draft:
            raise HTTPException(status_code=404, detail=f"找不到 draft_id={draft_id}")

        approval = conn.execute(
            "SELECT * FROM approval_requests WHERE draft_id = ?", (draft_id,)
        ).fetchone()

    # 🛡️ 強制攔截：沒有 approval 或是狀態不是 approved，一律拒絕發布！
    if not approval or approval["status"] != "approved":
        current_status = approval["status"] if approval else "missing"
        raise HTTPException(
            status_code=403,
            detail={
                "error": "PUBLISH_REJECTED_NO_APPROVAL",
                "message": "拒絕發布：此草稿尚未通過審核 (Approval Required)！",
                "draft_id": draft_id,
                "approval_status": current_status,
            },
        )

    if draft["status"] == "published":
        raise HTTPException(status_code=400, detail="此草稿已經發布過了！")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 階段 A：建立 IG Media Container
        container_ep = f"/{ig_user_id}/media"
        c_resp = await client.post(
            f"https://graph.facebook.com/{API_VER}{container_ep}",
            data={
                "image_url": draft["image_url"],
                "caption": draft["caption"],
                "access_token": access_token,
            },
        )
        c_json = c_resp.json()
        c_err = log_api_call(container_ep, c_resp.status_code, c_json)
        if c_err["is_error"]:
            raise HTTPException(status_code=c_resp.status_code, detail={"step": "create_container", "api_error": c_err})

        creation_id = c_json["id"]

        # 階段 B：正式發布 Media Container
        publish_ep = f"/{ig_user_id}/media_publish"
        pub_resp = await client.post(
            f"https://graph.facebook.com/{API_VER}{publish_ep}",
            data={
                "creation_id": creation_id,
                "access_token": access_token,
            }, 
        )
        pub_json = pub_resp.json()
        pub_err = log_api_call(publish_ep, pub_resp.status_code, pub_json)
        if pub_err["is_error"]:
            raise HTTPException(status_code=pub_resp.status_code, detail={"step": "media_publish", "api_error": pub_err})

        published_media_id = pub_json["id"]
        now_iso = datetime.now(timezone.utc).isoformat()

        # 更新 Draft 狀態並寫入一筆發布事件到 external_observations
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE post_drafts SET status = 'published', published_media_id = ?, updated_at = ? WHERE id = ?",
                (published_media_id, now_iso, draft_id),
            )
            conn.execute(
                """
                INSERT INTO external_observations (ig_user_id, observation_type, external_id, payload_json, observed_at)
                VALUES (?, 'media_published_event', ?, ?, ?)
                """,
                (
                    ig_user_id,
                    published_media_id,
                    json.dumps({"draft_id": draft_id, "creation_id": creation_id, "media_id": published_media_id}),
                    now_iso,
                ),
            )

    return {
        "message": "貼文發布成功！",
        "draft_id": draft_id,
        "creation_id": creation_id,
        "published_media_id": published_media_id,
    }


@app.post("/posts/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, reviewer: str = "admin"):
    """
    3. 核准審核請求 (Approve Approval Request)
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE approval_requests SET status = 'approved', reviewer = ?, reviewed_at = ? WHERE draft_id = ?",
            (reviewer, now_iso, draft_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"找不到 draft_id={draft_id} 的審核請求")
        conn.execute(
            "UPDATE post_drafts SET status = 'approved', updated_at = ? WHERE id = ?",
            (now_iso, draft_id),
        )
    return {
        "message": f"Draft {draft_id} 已核准 (approved)！現在可以呼叫 publish 端點進行發布。",
        "draft_id": draft_id,
        "approval_status": "approved",
        "reviewer": reviewer,
        "reviewed_at": now_iso,
    }

@app.get("/ig/posts/{media_id}/insights")
async def get_media_insights(media_id: str):
    """
    Read Operation: 讀取指定貼文的詳細成效洞察數據 (Insights)
    """
    conn_row, access_token = get_active_connection()
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. 讀取貼文基礎資訊
        media_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}/{media_id}",
            params={
                "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                "access_token": access_token,
            },
        )
        # 2. 讀取深度 Insights 指標
        insights_resp = await client.get(
            f"https://graph.facebook.com/{API_VER}/{media_id}/insights",
            params={
                "metric": "reach,total_interactions",
                "access_token": access_token,
            },
        )
        
        m_json = media_resp.json()
        i_json = insights_resp.json()
        
        log_api_call(f"/{media_id}", media_resp.status_code, m_json)
        log_api_call(f"/{media_id}/insights", insights_resp.status_code, i_json)

    return {
        "media_info": m_json,
        "insights": i_json.get("data", i_json),
    }
