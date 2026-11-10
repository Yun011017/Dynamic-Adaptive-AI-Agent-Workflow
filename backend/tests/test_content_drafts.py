import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.content_drafts import meta_adapter_payload
from app.schemas import ContentDraftCreate


class MetaAdapterPayloadTests(unittest.TestCase):
    def test_scheduled_single_post_requires_an_image(self):
        with self.assertRaises(ValidationError):
            ContentDraftCreate(
                caption="Build with us",
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
                schedule_requested=True,
            )

    def test_scheduled_carousel_requires_two_images(self):
        with self.assertRaises(ValidationError):
            ContentDraftCreate(
                caption="Build with us",
                carousel=True,
                image_requirements=["Cover", "Project"],
                image_urls=["https://images.example.test/cover.jpg"],
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
                schedule_requested=True,
            )

    def test_single_image_payload(self):
        payload = meta_adapter_payload(
            caption="Build with us",
            hashtags=["NTUMaker"],
            image_urls=["https://images.example.test/cover.jpg"],
            carousel=False,
        )
        self.assertEqual(payload["media_type"], "IMAGE")
        self.assertEqual(payload["image_url"], "https://images.example.test/cover.jpg")
        self.assertEqual(payload["caption"], "Build with us\n\n#NTUMaker")

    def test_video_requirements_are_preserved(self):
        draft = ContentDraftCreate(
            caption="Build with us",
            video_requirements=[" 15 秒短影音，呈現實作過程 ", ""],
        )
        self.assertEqual(draft.video_requirements, ["15 秒短影音，呈現實作過程"])

    def test_carousel_payload_contains_every_image(self):
        payload = meta_adapter_payload(
            caption="Build with us",
            hashtags=["NTUMaker", "3D列印"],
            image_urls=[
                "https://images.example.test/cover.jpg",
                "https://images.example.test/project.jpg",
            ],
            carousel=True,
        )
        self.assertEqual(payload["media_type"], "CAROUSEL")
        self.assertEqual(
            payload["children"],
            [
                {"image_url": "https://images.example.test/cover.jpg", "is_carousel_item": True},
                {"image_url": "https://images.example.test/project.jpg", "is_carousel_item": True},
            ],
        )
        self.assertEqual(payload["caption"], "Build with us\n\n#NTUMaker #3D列印")

    def test_reel_payload_uses_one_video_url(self):
        payload = meta_adapter_payload(
            caption="Watch us build",
            hashtags=["NTUMaker"],
            image_urls=[],
            video_urls=["https://videos.example.test/reel.mp4"],
            carousel=False,
            post_format="reel",
        )
        self.assertEqual(payload["media_type"], "REELS")
        self.assertEqual(payload["video_url"], "https://videos.example.test/reel.mp4")

    def test_mixed_carousel_payload_contains_image_and_video_children(self):
        payload = meta_adapter_payload(
            caption="Build with us",
            hashtags=[],
            image_urls=["https://images.example.test/cover.jpg"],
            video_urls=["https://videos.example.test/process.mp4"],
            carousel=True,
            post_format="mixed_carousel",
        )
        self.assertEqual(payload["media_type"], "CAROUSEL")
        self.assertEqual(
            payload["children"],
            [
                {"media_type": "IMAGE", "image_url": "https://images.example.test/cover.jpg", "is_carousel_item": True},
                {"media_type": "VIDEO", "video_url": "https://videos.example.test/process.mp4", "is_carousel_item": True},
            ],
        )


if __name__ == "__main__":
    unittest.main()
