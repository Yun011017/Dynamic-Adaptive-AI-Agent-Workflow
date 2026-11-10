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
    async def wait_for_video_container(
        client: httpx.AsyncClient, *, api_ver: str, container_id: str, access_token: str
    ) -> None:
        """Meta processes video containers asynchronously before they can be published."""
        for _ in range(30):
            response = await client.get(
                f"https://graph.facebook.com/{api_ver}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            payload = response.json()
            status = payload.get("status_code")
            if response.status_code == 200 and status == "FINISHED":
                return
            if response.status_code != 200 or status in {"ERROR", "EXPIRED"}:
                raise RuntimeError(f"Video container processing failed: {payload}")
            await asyncio.sleep(2)
        raise RuntimeError("Video container processing timed out")

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

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
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
                    container_resp = await client.post(
                        f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media",
                        data={
                            "media_type": "REELS",
                            "video_url": meta_payload["video_url"],
                            "caption": caption,
                            "access_token": access_token,
                        },
                    )
                    c_data = container_resp.json()
                    if container_resp.status_code != 200 or "id" not in c_data:
                        raise RuntimeError(f"Failed to create Reel container: {c_data}")
                    creation_id = c_data["id"]
                    await InstagramPublisherService.wait_for_video_container(
                        client, api_ver=api_ver, container_id=creation_id, access_token=access_token
                    )

                elif media_type == "CAROUSEL":
                    children_ids = []
                    for child in meta_payload.get("children", []):
                        child_data = {
                            "is_carousel_item": "true",
                            "access_token": access_token,
                        }
                        if child.get("media_type") == "VIDEO":
                            child_data.update({
                                "media_type": "VIDEO",
                                "video_url": child["video_url"],
                            })
                        else:
                            child_data["image_url"] = child["image_url"]
                        child_resp = await client.post(
                            f"https://graph.facebook.com/{api_ver}/{ig_user_id}/media",
                            data=child_data,
                        )
                        ch_data = child_resp.json()
                        if child_resp.status_code != 200 or "id" not in ch_data:
                            raise RuntimeError(f"Failed to create carousel child container: {ch_data}")
                        children_ids.append(ch_data["id"])
                        if child.get("media_type") == "VIDEO":
                            await InstagramPublisherService.wait_for_video_container(
                                client, api_ver=api_ver, container_id=ch_data["id"], access_token=access_token
                            )

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

                # 發布 Media Container
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
