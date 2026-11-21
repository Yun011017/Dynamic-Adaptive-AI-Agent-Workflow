import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from unittest.mock import patch, MagicMock

import httpx
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.config import settings
from app.content_drafts import _payload
from app.main import execute_action
from app.models import ExecutionAction, ApprovalRequest
from app.schemas import ContentDraftCreate, PublishActionRequest
from app.services.approval_service import ApprovalService

class ApprovalAndPublishTests(unittest.TestCase):
    async def _exercise_video_publish(self):
        url = "https://cdn.example.test/reel.mp4"
        draft = ContentDraftCreate(caption="Watch us build", video_url=url)
        payload = _payload(MagicMock(id=1, version=1), draft)
        self.assertEqual(payload["post_format"], "reel")
        self.assertEqual(payload["video_urls"], [url])
        payload["scheduled_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        action = ExecutionAction(id=1, draft_version=1, status="SCHEDULED", content_hash="hash", payload=payload)
        approval = ApprovalRequest(status="APPROVED", content_hash="hash")
        db = MagicMock()
        db.scalar.side_effect = [action, action, approval]
        requests = []

        def meta_response(request):
            requests.append(request)
            responses = [
                {"id": "container"},
                {"status_code": "FINISHED"},
                {"id": "published-reel"},
            ]
            return httpx.Response(200, json=responses[len(requests) - 1])

        meta = httpx.AsyncClient(transport=httpx.MockTransport(meta_response))
        with (
            patch.object(settings, "meta_access_token", SecretStr("token")),
            patch.object(settings, "meta_ig_user_id", "account"),
            patch("app.services.publisher_service.httpx.AsyncClient", return_value=meta),
        ):
            with self.assertRaises(ValidationError):
                PublishActionRequest(video_url="http://example.test/reel.mp4")
            with self.assertRaises(HTTPException) as mismatch:
                await execute_action(1, db, 1, PublishActionRequest(video_url="https://example.test/other.mp4"))
            self.assertEqual(mismatch.exception.status_code, 409)
            self.assertEqual(requests, [])
            response = await execute_action(1, db, 1, PublishActionRequest(video_url=url))

        self.assertEqual(response["external_id"], "published-reel")
        self.assertEqual(action.status, "SUCCEEDED")
        self.assertEqual([request.method for request in requests], ["POST", "GET", "POST"])
        self.assertTrue(requests[0].url.path.endswith("/account/media"))
        self.assertEqual(parse_qs(requests[0].content.decode())["video_url"], [url])
        self.assertTrue(requests[1].url.path.endswith("/container"))
        self.assertTrue(requests[2].url.path.endswith("/account/media_publish"))

    def test_execute_sends_only_the_approved_video_url_to_meta(self):
        asyncio.run(self._exercise_video_publish())

    def test_unapproved_action_blocks_publish(self):
        action = ExecutionAction(
            id=1,
            workspace_id=1,
            draft_version=1,
            content_hash="test_hash",
            status="DRAFT"
        )
        approval = None
        with self.assertRaises(HTTPException) as cm:
            ApprovalService.verify_publish_preconditions(approval, action, oauth_valid=True)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(cm.exception.detail["error"], "PUBLISH_REJECTED_NO_APPROVAL")

    def test_content_hash_mismatch_blocks_publish(self):
        action = ExecutionAction(
            id=1,
            workspace_id=1,
            draft_version=1,
            content_hash="tampered_hash",
            status="APPROVED"
        )
        approval = ApprovalRequest(
            id=1,
            workspace_id=1,
            action_id=1,
            draft_version=1,
            content_hash="original_hash",
            status="APPROVED",
            expires_at=None
        )
        with self.assertRaises(HTTPException) as cm:
            ApprovalService.verify_publish_preconditions(approval, action, oauth_valid=True)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["error"], "CONTENT_HASH_MISMATCH")

    def test_approval_decision_workflow(self):
        db = MagicMock()
        action = ExecutionAction(
            id=1,
            workspace_id=1,
            draft_version=1,
            content_hash="valid_hash",
            status="PENDING_REVIEW",
            payload={"scheduled_at": "2030-01-01T00:00:00+00:00"},
        )
        approval = ApprovalRequest(
            id=1,
            workspace_id=1,
            action_id=1,
            draft_version=1,
            content_hash="valid_hash",
            status="PENDING_REVIEW"
        )
        # 核准
        ApprovalService.process_decision(db, approval=approval, action=action, decision="approved", reason="OK")
        self.assertEqual(approval.status, "APPROVED")
        self.assertEqual(action.status, "SCHEDULED")

    def test_approved_draft_can_change_only_its_schedule_without_reapproval(self):
        db = MagicMock()
        original_hash = "approved-content-hash"
        action = ExecutionAction(
            id=4,
            workspace_id=1,
            draft_version=2,
            content_hash=original_hash,
            status="SCHEDULED",
            payload={
                "caption": "已核准的文案",
                "image_urls": ["https://cdn.example.test/cover.jpg"],
                "scheduled_at": "2030-01-01T00:00:00+00:00",
            },
        )
        approval = ApprovalRequest(
            id=4,
            workspace_id=1,
            action_id=4,
            draft_version=2,
            content_hash=original_hash,
            status="APPROVED",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        new_time = datetime.now(timezone.utc) + timedelta(days=7)

        ApprovalService.reschedule_approved_action(
            db, action=action, approval=approval, scheduled_at=new_time
        )

        self.assertEqual(action.status, "SCHEDULED")
        self.assertEqual(action.content_hash, original_hash)
        self.assertEqual(action.payload["caption"], "已核准的文案")
        self.assertEqual(action.payload["scheduled_at"], new_time.isoformat())
        self.assertTrue(action.payload["schedule_requested"])
        self.assertGreaterEqual(approval.expires_at, new_time + timedelta(hours=1))

    def test_rescheduling_requires_an_approved_scheduled_draft(self):
        with self.assertRaises(HTTPException) as error:
            ApprovalService.reschedule_approved_action(
                MagicMock(),
                action=ExecutionAction(status="DRAFT"),
                approval=ApprovalRequest(status="APPROVED"),
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_revision_request_returns_draft_to_editing(self):
        db = MagicMock()
        action = ExecutionAction(
            id=2,
            workspace_id=1,
            draft_version=1,
            content_hash="valid_hash",
            status="PENDING_REVIEW",
            payload={"scheduled_at": "2030-01-01T00:00:00+00:00"},
        )
        approval = ApprovalRequest(
            id=2,
            workspace_id=1,
            action_id=2,
            draft_version=1,
            content_hash="valid_hash",
            status="PENDING_REVIEW",
        )

        ApprovalService.process_decision(
            db, approval=approval, action=action, decision="needs_revision", reason="補上素材"
        )

        self.assertEqual(approval.status, "REJECTED")
        self.assertEqual(action.status, "DRAFT")

    @patch("app.services.approval_service.validate_action_media")
    def test_submit_for_review_checks_public_media_before_queueing(self, check_media):
        db = MagicMock()
        action = ExecutionAction(
            id=3,
            workspace_id=1,
            draft_version=1,
            content_hash="valid_hash",
            status="DRAFT",
            payload={
                "scheduled_at": "2030-01-01T00:00:00+00:00",
                "post_format": "image",
                "image_requirements": ["封面圖"],
                "image_urls": ["https://cdn.example.test/cover.jpg"],
                "video_urls": [],
                "meta_adapter_payload": {"media_type": "IMAGE"},
            },
        )

        approval = ApprovalService.submit_for_review(db, action=action)

        check_media.assert_called_once_with(action)
        self.assertEqual(action.status, "PENDING_REVIEW")

    @patch("app.services.approval_service.validate_action_media")
    def test_manual_public_video_url_can_submit_without_video_requirement(self, check_media):
        db = MagicMock()
        action = ExecutionAction(
            id=4,
            workspace_id=1,
            draft_version=1,
            content_hash="valid_hash",
            status="DRAFT",
            payload={
                "scheduled_at": "2030-01-01T00:00:00+00:00",
                "post_format": "reel",
                "image_requirements": [],
                "video_requirements": [],
                "image_urls": [],
                "video_urls": ["https://cdn.example.test/reel.mp4"],
                "meta_adapter_payload": {"media_type": "REELS"},
            },
        )

        approval = ApprovalService.submit_for_review(db, action=action)

        check_media.assert_called_once_with(action)
        self.assertEqual(action.status, "PENDING_REVIEW")
        self.assertEqual(approval.status, "PENDING_REVIEW")
        self.assertEqual(approval.status, "PENDING_REVIEW")



if __name__ == "__main__":
    unittest.main()


@patch("app.services.publisher_service.httpx.AsyncClient.post")
def test_single_image_publish_success(self, mock_post):
    import asyncio
    from unittest.mock import AsyncMock
    from app.services.publisher_service import InstagramPublisherService

    # 模擬 Meta 兩階段呼叫 (建立 container -> 發布)
    mock_container_resp = AsyncMock()
    mock_container_resp.status_code = 200
    mock_container_resp.json.return_value = {"id": "container_123"}

    mock_publish_resp = AsyncMock()
    mock_publish_resp.status_code = 200
    mock_publish_resp.json.return_value = {"id": "media_post_456"}

    mock_post.side_effect = [mock_container_resp, mock_publish_resp]

    action = ExecutionAction(
        id=10,
        workspace_id=1,
        draft_version=1,
        content_hash="valid_hash",
        status="APPROVED",
        payload={
            "meta_adapter_payload": {
                "media_type": "IMAGE",
                "image_url": "https://images.example.test/cover.jpg",
                "caption": "Test Caption #NTUMaker",
            }
        },
    )
    approval = ApprovalRequest(
        id=1,
        workspace_id=1,
        action_id=10,
        draft_version=1,
        content_hash="valid_hash",
        status="APPROVED",
        expires_at=None,
    )
    db = MagicMock()

    with patch.dict("os.environ", {"META_ACCESS_TOKEN": "token", "META_IG_USER_ID": "ig_123"}):
        external_id = asyncio.run(InstagramPublisherService.publish_action(db, action, approval))

    self.assertEqual(external_id, "media_post_456")
    self.assertEqual(action.status, "SUCCEEDED")
    self.assertEqual(action.external_id, "media_post_456")
    db.commit.assert_called()

@patch("app.services.publisher_service.httpx.AsyncClient.post")
def test_carousel_publish_success(self, mock_post):
    import asyncio
    from unittest.mock import AsyncMock
    from app.services.publisher_service import InstagramPublisherService

    # 輪播先建 2 個 child container，再建 1 個 parent container，最後 media_publish
    c1 = AsyncMock(status_code=200)
    c1.json.return_value = {"id": "child_1"}
    c2 = AsyncMock(status_code=200)
    c2.json.return_value = {"id": "child_2"}
    parent = AsyncMock(status_code=200)
    parent.json.return_value = {"id": "parent_carousel"}
    published = AsyncMock(status_code=200)
    published.json.return_value = {"id": "final_carousel_post"}

    mock_post.side_effect = [c1, c2, parent, published]

    action = ExecutionAction(
        id=11,
        workspace_id=1,
        draft_version=1,
        content_hash="valid_hash",
        status="APPROVED",
        payload={
            "meta_adapter_payload": {
                "media_type": "CAROUSEL",
                "children": [
                    {"image_url": "https://img.test/1.jpg"},
                    {"image_url": "https://img.test/2.jpg"},
                ],
                "caption": "Carousel Caption",
            }
        },
    )
    approval = ApprovalRequest(
        id=2,
        workspace_id=1,
        action_id=11,
        draft_version=1,
        content_hash="valid_hash",
        status="APPROVED",
        expires_at=None,
    )
    db = MagicMock()

    with patch.dict("os.environ", {"META_ACCESS_TOKEN": "token", "META_IG_USER_ID": "ig_123"}):
        external_id = asyncio.run(InstagramPublisherService.publish_action(db, action, approval))

    self.assertEqual(external_id, "final_carousel_post")
    self.assertEqual(action.status, "SUCCEEDED")
    self.assertEqual(mock_post.call_count, 4)

@patch("app.services.publisher_service.httpx.AsyncClient.post")
def test_publish_failure_marks_action_failed(self, mock_post):
    import asyncio
    from unittest.mock import AsyncMock
    from app.services.publisher_service import InstagramPublisherService

    mock_resp = AsyncMock(status_code=400)
    mock_resp.json.return_value = {"error": {"message": "Invalid OAuth token"}}
    mock_post.return_value = mock_resp

    action = ExecutionAction(
        id=12,
        workspace_id=1,
        draft_version=1,
        content_hash="valid_hash",
        status="APPROVED",
        payload={
            "meta_adapter_payload": {
                "media_type": "IMAGE",
                "image_url": "https://img.test/fail.jpg",
            }
        },
    )
    approval = ApprovalRequest(
        id=3,
        workspace_id=1,
        action_id=12,
        draft_version=1,
        content_hash="valid_hash",
        status="APPROVED",
        expires_at=None,
    )
    db = MagicMock()

    with patch.dict("os.environ", {"META_ACCESS_TOKEN": "token", "META_IG_USER_ID": "ig_123"}):
        with self.assertRaises(RuntimeError):
            asyncio.run(InstagramPublisherService.publish_action(db, action, approval))

    self.assertEqual(action.status, "FAILED")
    db.commit.assert_called()
