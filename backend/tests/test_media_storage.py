import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import SecretStr

from app.config import settings
from app.services.media_storage import _assert_declared_upload, create_direct_upload


class R2MediaStorageTests(unittest.TestCase):
    def _configured_r2(self):
        stack = ExitStack()
        stack.enter_context(patch.object(settings, "r2_account_id", "account-123"))
        stack.enter_context(patch.object(settings, "r2_access_key_id", "key-123"))
        stack.enter_context(patch.object(settings, "r2_secret_access_key", SecretStr("secret-123")))
        stack.enter_context(patch.object(settings, "r2_bucket_name", "instagram-media"))
        stack.enter_context(patch.object(settings, "r2_public_base_url", "https://media.example.test"))
        return stack

    @patch("app.services.media_storage.boto3.client")
    def test_creates_direct_upload_for_workspace_prefix(self, client_factory):
        client = MagicMock()
        client.generate_presigned_post.return_value = {"url": "https://r2.example/upload", "fields": {"key": "signed-key"}}
        client_factory.return_value = client
        db = MagicMock()
        db.flush.side_effect = lambda: setattr(db.add.call_args.args[0], "id", 12)
        with self._configured_r2():
            upload = create_direct_upload(
                db=db, workspace_id=8, media_type="image", filename="cover.jpg",
                content_type="image/jpeg", size_bytes=123,
            )

        self.assertEqual(upload["asset_id"], 12)
        self.assertTrue(upload["url"].startswith("https://media.example.test/workspaces/8/instagram/images/"))
        client.generate_presigned_post.assert_called_once()
        self.assertEqual(client.generate_presigned_post.call_args.args[0], "instagram-media")

    def test_rejects_mismatched_file_type(self):
        with self.assertRaises(HTTPException) as error:
            _assert_declared_upload(media_type="image", filename="not-image.jpg", content_type="text/plain", size_bytes=10)
        self.assertEqual(error.exception.status_code, 422)

    def test_accepts_common_jpg_mime_alias(self):
        extension = _assert_declared_upload(
            media_type="image", filename="cover.jpg", content_type="image/jpg", size_bytes=10,
        )
        self.assertEqual(extension, ".jpg")

    def test_rejects_a_file_larger_than_limit(self):
        with patch.object(settings, "r2_max_upload_bytes", 100):
            with self.assertRaises(HTTPException) as error:
                _assert_declared_upload(media_type="video", filename="clip.mp4", content_type="video/mp4", size_bytes=101)
        self.assertEqual(error.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
