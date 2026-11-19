import asyncio
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.models import ExecutionAction, ApprovalRequest
from app.services.approval_service import ApprovalService


class InstagramPublisherService:
    @staticmethod
    def check_oauth_status() -> bool:
        token = settings.meta_access_token.get_secret_value() if settings.meta_access_token else ""
        return bool(token.strip() and settings.meta_ig_user_id.strip())

    @staticmethod
    async def _wait_container_ready(
        client: httpx.AsyncClient,
        creation_id: str,
        access_token: str,
        api_ver: str,
        max_attempts: int = 30,
        interval_sec: float = 2.0,
    ) -> None:
        """輪詢等待 Meta 伺服器處理完圖片或影片 Container，直到 status_code == FINISHED"""
        last_data = {}
        for _ in range(max_attempts):
            res = await client.get(
                f"https://graph.facebook.com/{api_ver}/{creation_id}",
                params={"fields": "status_code,status", "access_token": access_token},
            )
            last_data = res.json()
            status = last_data.get("status_code")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise RuntimeError(f"Container {creation_id} processing failed: {last_data}")
            await asyncio.sleep(interval_sec)

        raise TimeoutError(
            f"Container {creation_id} did not reach FINISHED within {max_attempts * interval_sec}s: {last_data}"
        )

    @staticmethod
    async def publish_action(db: Session, action: ExecutionAction, approval: ApprovalRequest | None) -> str:
        oauth_ready = InstagramPublisherService.check_oauth_status()
        ApprovalService.verify_publish_preconditions(approval, action, oauth_valid=oauth_ready)

        access_token = settings.meta_access_token.get_secret_value()
        ig_user_id = settings.meta_ig_user_id
        api_ver = settings.graph_api_version

        meta_payload = action.payload.get("meta_adapter_payload")
        if not meta_payload:
            raise ValueError("Missing meta_adapter_payload in action payload")

        media_type = meta_payload.get("media_type")
        caption = meta_payload.get("caption", "")

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # 1. 依類型建立 Media Container
                if media_type == "IMAGE":
                    container_resp = await client.post(
                        f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media",
                        data={
                            "image_url": meta_payload["image_url"],
                            "caption": caption,
                            "access_token": access_token,
                        },
                    )
                    c_data = container_resp.json()
                    if container_resp.status_code != 200 or "id" not in c_data:
                        raise RuntimeError(f"Failed to create media container: {c_data}")
                    creation_id = c_data["id"]

                elif media_type == "REELS":
                    video_url = meta_payload.get("video_url") or meta_payload.get("media_url")
                    container_resp = await client.post(
                        f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media",
                        data={
                            "media_type": "REELS",
                            "video_url": video_url,
                            "caption": caption,
                            "access_token": access_token,
                        },
                    )
                    c_data = container_resp.json()
                    if container_resp.status_code != 200 or "id" not in c_data:
                        raise RuntimeError(f"Failed to create reels container: {c_data}")
                    creation_id = c_data["id"]

                elif media_type == "CAROUSEL":
                    children_ids = []
                    for child in meta_payload.get("children", []):
                        child_type = child.get("media_type", "IMAGE")
                        child_form = {
                            "is_carousel_item": "true",
                            "access_token": access_token,
                        }
                        if child_type == "VIDEO":
                            child_form["media_type"] = "VIDEO"
                            child_form["video_url"] = child.get("video_url") or child.get("media_url")
                        else:
                            child_form["image_url"] = child.get("image_url") or child.get("media_url")

                        child_resp = await client.post(
                            f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media",
                            data=child_form,
                        )
                        ch_data = child_resp.json()
                        if child_resp.status_code != 200 or "id" not in ch_data:
                            raise RuntimeError(f"Failed to create carousel child container: {ch_data}")
                        child_id = ch_data["id"]

                        # 子容器若是影片，必須先等 Meta 轉檔為 FINISHED 再組裝母容器
                        if child_type == "VIDEO":
                            await InstagramPublisherService._wait_container_ready(
                                client, child_id, access_token, api_ver
                            )
                        children_ids.append(child_id)

                    parent_resp = await client.post(
                        f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media",
                        data={
                            "media_type": "CAROUSEL",
                            "children": ",".join(children_ids),
                            "caption": caption,
                            "access_token": access_token,
                        },
                    )
                    p_data = parent_resp.json()
                    if parent_resp.status_code != 200 or "id" not in p_data:
                        raise RuntimeError(f"Failed to create carousel parent container: {p_data}")
                    creation_id = p_data["id"]

                else:
                    raise ValueError(f"Unsupported media_type: {media_type}")

                # 2. 輪詢等待主 Container 達到 FINISHED
                await InstagramPublisherService._wait_container_ready(
                    client, creation_id, access_token, api_ver
                )

                # 3. 正式發布 Media Container
                pub_resp = await client.post(
                    f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media_publish",
                    data={
                        "creation_id": creation_id,
                        "access_token": access_token,
                    },
                )
                pub_data = pub_resp.json()
                if pub_resp.status_code != 200 or "id" not in pub_data:
                    raise RuntimeError(f"Failed to publish media: {pub_data}")

                external_id = pub_data["id"]
                action.external_id = external_id
                action.status = "SUCCEEDED"
                db.commit()
                return external_id

            except Exception as e:
                action.status = "FAILED"
                db.commit()
                raise e