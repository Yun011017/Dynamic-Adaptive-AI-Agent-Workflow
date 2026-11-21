"""Safe, user-visible publishing outcomes stored with a content proposal."""

from datetime import datetime, timezone

from app.models import ExecutionAction


def _failure_message(error: Exception) -> str:
    """Return a useful reason without persisting credentials or raw API responses."""
    detail = str(error).lower()
    if "access token" in detail or "oauth" in detail:
        return "Meta 存取權杖無效、已過期或缺少發布權限。"
    if "timed out" in detail or "timeout" in detail:
        return "等待 Meta 處理素材逾時，請確認影片格式與公開網址後重試。"
    if "video container" in detail:
        return "Meta 無法完成影片素材處理，請確認影片格式與公開網址。"
    if "carousel child" in detail:
        return "Meta 無法建立多素材貼文的其中一項素材，請確認所有素材網址可公開讀取。"
    if "media container" in detail or "reel container" in detail:
        return "Meta 無法建立貼文素材，請確認帳號權限與素材公開網址。"
    if "publish media" in detail or "media_publish" in detail:
        return "Meta 未能完成貼文發布，請確認帳號權限後再建立新版本重試。"
    return "發布失敗，請確認 Meta 帳號權限、素材公開網址與排程設定。"


def _with_publish_result(action: ExecutionAction, result: dict) -> None:
    payload = dict(action.payload or {})
    payload["publish_result"] = result
    action.payload = payload


def record_publish_success(action: ExecutionAction, external_id: str) -> None:
    _with_publish_result(
        action,
        {
            "status": "SUCCEEDED",
            "external_id": external_id,
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def record_publish_failure(action: ExecutionAction, error: Exception) -> None:
    _with_publish_result(
        action,
        {
            "status": "FAILED",
            "message": _failure_message(error),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
