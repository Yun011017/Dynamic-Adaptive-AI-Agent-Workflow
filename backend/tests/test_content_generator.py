import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.content_generator import generate_content_draft, revise_content_draft_with_agent
from app.schemas import ContentDraftCreate


def goal(signup_url="https://example.test/register"):
    constraints = {"channel": "instagram"}
    if signup_url:
        constraints["signup_url"] = signup_url
    return SimpleNamespace(
        id=3,
        title="新手創客工作坊",
        description="零基礎學生的實作活動",
        constraints=constraints,
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
        self.assertEqual(result.signup_url, "https://example.test/register")
        self.assertIn("https://example.test/register", result.caption)

    def test_local_provider_can_return_a_single_image_draft(self):
        result = generate_content_draft(
            goal=goal(signup_url=None),
            strategy=strategy(),
            provider="local",
            model_name="deterministic-langgraph",
            content_format="single",
        )
        self.assertFalse(result.carousel)
        self.assertEqual(len(result.image_requirements), 1)
        self.assertEqual(result.image_urls, [])
        self.assertNotIn("報名入口", result.caption)

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

    def test_agent_revision_returns_a_complete_safe_suggestion(self):
        class FakeModel:
            def invoke(self, _messages):
                return SimpleNamespace(content=json.dumps({
                    "reply": "已將開頭改得更聚焦新手的第一步。",
                    "suggestion": {
                        "title": "新手 Arduino 工作坊",
                        "caption": "從點亮第一顆 LED 開始。",
                        "hashtags": ["#NTUMaker", "Arduino"],
                        "image_requirements": ["4:5 直式封面，呈現麵包板與 LED。", "4:5 直式實作照，呈現接線過程。"],
                        "video_requirements": [],
                    },
                }, ensure_ascii=False))

        current = ContentDraftCreate(
            title="原始提案",
            caption="原本的文案。",
            hashtags=["NTUMaker"],
            image_requirements=["4:5 直式封面。", "4:5 直式作品照。"],
            carousel=True,
        )
        with patch("app.content_generator._model_for", return_value=FakeModel()):
            result = revise_content_draft_with_agent(
                goal=goal(), strategy=strategy(), current_draft=current,
                message="請讓新手更容易理解", provider="gemini", model_name="test-model",
            )
        self.assertEqual(result.suggestion.title, "新手 Arduino 工作坊")
        self.assertEqual(result.suggestion.hashtags, ["NTUMaker", "Arduino"])

