import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.content_generator import generate_content_draft


def goal():
    return SimpleNamespace(
        id=3,
        title="新手創客工作坊",
        description="零基礎學生的實作活動",
        constraints={"channel": "instagram"},
    )


def strategy():
    return SimpleNamespace(
        id=12,
        version=1,
        content="強調學生能完成自己的第一件實作作品。",
        rationale="表單回覆顯示實作成果最能降低新手參與門檻。",
    )


class ContentGeneratorTests(unittest.TestCase):
    def test_local_provider_returns_a_safe_carousel_draft(self):
        result = generate_content_draft(
            goal=goal(), strategy=strategy(), provider="local", model_name="deterministic-langgraph"
        )
        self.assertTrue(result.carousel)
        self.assertGreaterEqual(len(result.image_requirements), 2)
        self.assertEqual(result.image_urls, [])
        self.assertIn("新手創客工作坊", result.caption)

    def test_local_provider_can_return_a_single_image_draft(self):
        result = generate_content_draft(
            goal=goal(),
            strategy=strategy(),
            provider="local",
            model_name="deterministic-langgraph",
            content_format="single",
        )
        self.assertFalse(result.carousel)
        self.assertEqual(len(result.image_requirements), 1)
        self.assertEqual(result.image_urls, [])

    def test_model_output_is_normalized_to_carousel_without_image_urls(self):
        class FakeModel:
            def invoke(self, _messages):
                return SimpleNamespace(content=json.dumps({
                    "caption": "一起做出第一件作品。",
                    "hashtags": ["#NTUMaker", "創客"],
                    "image_requirements": ["第 1 張封面", "第 2 張作品照"],
                    "image_urls": ["https://untrusted.example.test/invented.jpg"],
                    "carousel": False,
                }, ensure_ascii=False))

        with patch("app.content_generator._model_for", return_value=FakeModel()):
            result = generate_content_draft(
                goal=goal(), strategy=strategy(), provider="gemini", model_name="test-model"
            )
        self.assertTrue(result.carousel)
        self.assertEqual(result.image_urls, [])
        self.assertEqual(result.hashtags, ["NTUMaker", "創客"])

