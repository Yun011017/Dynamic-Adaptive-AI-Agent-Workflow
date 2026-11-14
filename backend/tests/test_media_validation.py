import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.services.media_validation import validate_action_media, validate_public_media_url


class MediaValidationTests(unittest.TestCase):
    def test_rejects_non_https_without_making_a_request(self):
        with self.assertRaises(ValueError):
            validate_public_media_url("http://example.test/image.jpg", expected_type="image")

    @patch("app.services.media_validation.validate_public_media_url")
    def test_checks_each_image_url_before_review(self, check_url):
        action = SimpleNamespace(payload={
            "post_format": "image",
            "image_urls": ["https://cdn.example.test/cover.jpg", "https://cdn.example.test/work.jpg"],
            "video_urls": [],
        })

        validate_action_media(action)

        self.assertEqual(
            check_url.call_args_list,
            [
                (("https://cdn.example.test/cover.jpg",), {"expected_type": "image"}),
                (("https://cdn.example.test/work.jpg",), {"expected_type": "image"}),
            ],
        )

    @patch("app.services.media_validation.validate_public_media_url", side_effect=ValueError("網址回應 HTTP 403"))
    def test_rejects_unreadable_media_with_actionable_error(self, _check_url):
        action = SimpleNamespace(payload={
            "post_format": "reel",
            "image_urls": [],
            "video_urls": ["https://cdn.example.test/reel.mp4"],
        })

        with self.assertRaises(HTTPException) as raised:
            validate_action_media(action)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("影片網址無法公開讀取", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
