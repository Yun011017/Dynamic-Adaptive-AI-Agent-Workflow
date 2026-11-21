import unittest

from app.models import ExecutionAction
from app.services.publishing_audit import record_publish_failure, record_publish_success


class PublishingAuditTests(unittest.TestCase):
    def test_success_stores_external_id_and_timestamp(self):
        action = ExecutionAction(payload={"title": "Test post"})

        record_publish_success(action, "meta-post-123")

        self.assertEqual(action.payload["title"], "Test post")
        self.assertEqual(action.payload["publish_result"]["status"], "SUCCEEDED")
        self.assertEqual(action.payload["publish_result"]["external_id"], "meta-post-123")
        self.assertIn("published_at", action.payload["publish_result"])

    def test_failure_keeps_a_safe_expired_token_reason(self):
        action = ExecutionAction(payload={})

        record_publish_failure(
            action,
            RuntimeError("Error validating access token: Session has expired"),
        )

        result = action.payload["publish_result"]
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("權杖", result["message"])
        self.assertIn("failed_at", result)


if __name__ == "__main__":
    unittest.main()
