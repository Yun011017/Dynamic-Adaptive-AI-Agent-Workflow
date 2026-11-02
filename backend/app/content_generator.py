"""Generate a safe, structured content draft from a persisted Strategy."""

from __future__ import annotations

import json
from datetime import datetime

from .agent_runner import _model_for
from .models import Goal, Strategy
from .schemas import ContentDraftCreate


class ContentDraftGenerationError(RuntimeError):
    """A provider reply did not satisfy the platform's draft contract."""


def _text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return str(content)


def _json_object(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1]
        candidate = candidate.rsplit("```", 1)[0].strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ContentDraftGenerationError("Content model did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ContentDraftGenerationError("Content model did not return an object")
    return value


def _local_draft(
    *, goal: Goal, strategy: Strategy, content_format: str, scheduled_at: datetime | None
) -> ContentDraftCreate:
    direction = strategy.content.strip()
    excerpt = direction[:1_600] if direction else "以活動特色與參與者可獲得的成果為主軸。"
    return ContentDraftCreate(
        title=f"{goal.title}：{('輪播' if content_format == 'carousel' else '單張')}內容提案",
        caption=(
            f"想更了解「{goal.title}」嗎？\n\n"
            f"{excerpt}\n\n"
            "歡迎查看活動資訊並完成報名。"
        )[:2_200],
        hashtags=["NTUMaker", "創客"],
        image_requirements=( [
            "第 1 張：1080×1080 封面，呈現活動主題與清楚的行動呼籲。",
            "第 2 張：學生或參與者的實作成果，呼應 Strategy 的內容方向。",
            "第 3 張：活動流程、可獲得的體驗或報名方式。",
        ] if content_format == "carousel" else [
            "單張：1080×1080 主視覺，呈現活動主題、實作成果與清楚的行動呼籲。"
        ] ),
        image_urls=[],
        carousel=content_format == "carousel",
        scheduled_at=scheduled_at,
    )


def generate_content_draft(
    *,
    goal: Goal,
    strategy: Strategy,
    provider: str,
    model_name: str,
    content_format: str = "carousel",
    scheduled_at: datetime | None = None,
) -> ContentDraftCreate:
    """Return validated platform data; image URLs are never invented by a model."""
    if provider == "local":
        return _local_draft(
            goal=goal,
            strategy=strategy,
            content_format=content_format,
            scheduled_at=scheduled_at,
        )

    model = _model_for(provider, model_name)
    prompt = {
        "goal": {"title": goal.title, "description": goal.description, "constraints": goal.constraints},
        "strategy": {"id": strategy.id, "version": strategy.version, "content": strategy.content, "rationale": strategy.rationale},
        "task": "產生一份 Instagram 內容草稿。",
        "rules": [
            "只使用提供的 Goal 與 Strategy，不可編造活動日期、地點、價格、成果或數字。",
            "以繁體中文輸出。",
            "只輸出 JSON object，欄位必須是 title、caption、hashtags、image_requirements、carousel。",
            "title 是 8 至 60 字的繁體中文提案名稱，用來區分不同內容提案。",
            "caption 不含 hashtag；hashtags 是不含 # 的字串陣列；image_requirements 是素材需求字串陣列。",
            "不可輸出 image_urls、token、帳號資訊或發布指令。",
            (
                "這是輪播貼文，carousel 必須為 true，且 image_requirements 必須列出至少兩張圖片的分頁需求。"
                if content_format == "carousel"
                else "這是單張貼文，carousel 必須為 false，且 image_requirements 只能描述一張主視覺。"
            ),
        ],
    }
    from langchain_core.messages import HumanMessage, SystemMessage

    response = model.invoke([
        SystemMessage(content="你是內容企劃助理。你必須遵守使用者提供的 JSON 規格與資料邊界。"),
        HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
    ])
    generated = _json_object(_text_content(response.content))
    generated.pop("image_urls", None)
    generated["channel"] = "instagram"
    generated.setdefault(
        "title",
        f"{goal.title}：{('輪播' if content_format == 'carousel' else '單張')}內容提案",
    )
    generated["carousel"] = content_format == "carousel"
    generated["scheduled_at"] = scheduled_at
    try:
        return ContentDraftCreate.model_validate(generated)
    except Exception as exc:
        raise ContentDraftGenerationError("Content model output did not match the draft contract") from exc
