import os
import httpx
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("META_ACCESS_TOKEN")
api_ver = os.getenv("GRAPH_API_VERSION", "v21.0")

if not token:
    print("[!] 未在 .env 找到 META_ACCESS_TOKEN，請先填入 Token。")
    raise SystemExit(1)

print("[*] 正在向 Meta Graph API 查詢綁定的粉專與 IG Business 帳號...\n")

resp = httpx.get(
    f"https://graph.facebook.com/{api_ver}/me/accounts",
    params={
        "fields": "id,name,instagram_business_account{id,username}",
        "access_token": token,
    },
)
data = resp.json()

if "error" in data:
    print(f"[!] Meta API 回報錯誤: {data['error']['message']}")
    raise SystemExit(1)

pages = data.get("data", [])
found_ig = False

print("=== 查詢結果 ===")
for page in pages:
    p_name = page.get("name")
    p_id = page.get("id")
    ig = page.get("instagram_business_account")
    
    print(f"粉專名稱: {p_name} (Page ID: {p_id})")
    if ig:
        ig_username = ig.get("username")
        ig_id = ig.get("id")
        print(f"  -> 找到 Instagram Business Account!")
        print(f"     IG 帳號: @{ig_username}")
        print(f"     正確的 META_IG_USER_ID={ig_id}\n")
        found_ig = True
    else:
        print("  -> 此粉專尚未連結 Instagram 商業／專業帳號。\n")

if not found_ig:
    # 嘗試反查目前的 ID
    current_id = os.getenv("META_IG_USER_ID")
    if current_id:
        check = httpx.get(
            f"https://graph.facebook.com/{api_ver}/{current_id}",
            params={"fields": "id,name,instagram_business_account{id,username}", "access_token": token},
        ).json()
        ig = check.get("instagram_business_account")
        if ig:
            print("從目前 ID 查得 Instagram Business Account:")
            print(f"META_IG_USER_ID={ig.get('id')}\n")
            found_ig = True

if not found_ig:
    print("----------------------------------------------------------------")
    print("診斷結論：")
    print("此 Token 存取的粉專尚未成功關聯 Instagram 商業帳號。")
    print("請確認：")
    print("1. Instagram 帳號已在 App 內切換為「商業帳號 (Business)」或「創作者帳號 (Creator)」。")
    print("2. 在 Facebook 粉專管理後台「設定」->「連結的帳號」->「Instagram」確認連線狀態為正常。")
    print("----------------------------------------------------------------")