import unittest

from app.content_drafts import meta_adapter_payload


class MetaAdapterPayloadTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
