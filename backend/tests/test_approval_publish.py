import unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from app.models import ExecutionAction, ApprovalRequest
from app.services.approval_service import ApprovalService

class ApprovalAndPublishTests(unittest.TestCase):
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
