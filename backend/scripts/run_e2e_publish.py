import os
from pathlib import Path
import requests
from dotenv import load_dotenv

# 1. 自動載入 backend/.env 設定
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
# 若 .env 沒有設定，預設使用純英文金鑰（避免任何中文進入 HTTP Header）
API_KEY = os.getenv("PLATFORM_API_KEY", "integration-test-key")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def run_flow():
    print(f"[*] API Base: {BASE_URL}")
    print(f"[*] API Key (前4碼): {API_KEY[:4]}***")

    # 1. 取得 Strategy ID
    res = requests.get(f"{BASE_URL}/strategies", headers=headers)
    if res.status_code != 200:
        print(f"[!] 取得 Strategies 失敗 ({res.status_code}): {res.text}")
        return

    strategies = res.json()
    if not strategies:
        print("[!] 尚未建立任何 Strategy，請先至後端 seed 或在 Dashboard 建立一個 Goal 與 Strategy。")
        return

    strategy_id = strategies[0]["id"]
    print(f"[1] 使用 Strategy ID: {strategy_id}")

    # 2. 建立含有公開真實 HTTPS 圖片的草稿 (單張測試)
    draft_payload = {
        "channel": "instagram",
        "title": "實體工作坊宣傳測試",
        "caption": "【NTUMaker 實戰除錯體驗】\n烙鐵燙桌子、感測器抓不到線？別慌，幹部陪跑除錯！\n\n#NTUMaker #自造者",
        "hashtags": ["NTUMaker", "自造者"],
        "image_requirements": ["1080x1080 主視覺"],
        "image_urls": ["https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=80"],
        "carousel": False,
        "scheduled_at": None,
        "schedule_requested": False,
    }
    draft_res = requests.post(
        f"{BASE_URL}/strategies/{strategy_id}/content-drafts",
        json=draft_payload,
        headers=headers,
    )
    if draft_res.status_code not in (200, 201):
        print(f"[!] 建立草稿失敗 ({draft_res.status_code}): {draft_res.text}")
        return

    draft = draft_res.json()
    action_id = draft["id"]
    print(f"[2] 草稿建立成功，Action ID: {action_id}, Status: {draft['status']}")

    # 3. 提交人工審核
    approval_res = requests.post(f"{BASE_URL}/actions/{action_id}/approval-requests", headers=headers)
    if approval_res.status_code not in (200, 201):
        print(f"[!] 提交審核失敗 ({approval_res.status_code}): {approval_res.text}")
        return

    approval = approval_res.json()
    approval_id = approval["id"]
    print(f"[3] 審核請求已建立，Approval ID: {approval_id}, Status: {approval['status']}")

    # 4. 驗證未核准直接發布會被 403 攔截
    blocked_res = requests.post(f"{BASE_URL}/actions/{action_id}/execute", headers=headers)
    print(f"[4] 未核准發布攔截測試狀態碼: {blocked_res.status_code} (預期 403: {blocked_res.json()})")

    # 5. 人工核准
    decision_res = requests.post(
        f"{BASE_URL}/approval-requests/{approval_id}/decision",
        json={"decision": "approved", "reason": "文案與圖片合規，准予發布"},
        headers=headers,
    )
    if decision_res.status_code != 200:
        print(f"[!] 審核操作失敗 ({decision_res.status_code}): {decision_res.text}")
        return
    print(f"[5] 審核完成，狀態已變更為: {decision_res.json()['status']}")

    # 6. 正式受控發布
    print("[6] 開始呼叫發布端點...")
    exec_res = requests.post(f"{BASE_URL}/actions/{action_id}/execute", headers=headers)
    if exec_res.status_code != 200:
        print(f"[!] 發布失敗 ({exec_res.status_code}): {exec_res.text}")
        return

    print(f"[7] 發布成功！回應內容: {exec_res.json()}")


if __name__ == "__main__":
    run_flow()