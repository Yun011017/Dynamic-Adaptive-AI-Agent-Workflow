"""Generate a safe, structured content draft from a persisted Strategy."""

from __future__ import annotations

import json
from datetime import datetime

from .agent_runner import _model_for
from .models import Goal, Strategy
from .schemas import ContentDraftCreate


CONTENT_SYSTEM_PROMPT = """你是 NTUMaker（臺大自造者社）的資深社群行銷幹部兼首席文案。

品牌核心是「Build. Learn. Share.」：NTUMaker 是以實作會友的交流聚落與創意實驗所；歡迎零基礎、也歡迎自帶點子的同學。社群常見的真實場景包含 3D 列印、雷射切割、Arduino、ESP32、CAD、PCB、感測器與 Web 開發。

文案要親民、專業、具體而有溫度：可使用工程開發中的除錯、卡關、零件裝反或非預期狀況作為幽默，但不得空泛裝熟或過度自嘲。優先寫出實體物件、技術名詞、操作動作、觸感或現場畫面，不要用空洞的行銷形容詞。以短句、適當斷行與少量 Emoji 作為視覺引導；排版清楚好讀。

一則貼文只能有一個明確 CTA。不可為了湊文案編造日期、地點、價格、報名連結、成果數字或活動細節；只可使用提供的 Goal 與 Strategy。若資料不足，維持泛用但具體的行動呼籲，不可補造事實。"""


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
    *, goal: Goal, strategy: Strategy, content_format: str, scheduled_at: datetime | None,
    schedule_requested: bool = False,
) -> ContentDraftCreate:
    direction = strategy.content.strip()
    excerpt = direction[:1_600] if direction else "以活動特色與參與者可獲得的成果為主軸。"
    return ContentDraftCreate(
        post_format="reel" if content_format == "reel" else "mixed_carousel" if content_format == "mixed_carousel" else "image",
        title=f"{goal.title}：{('多張圖片' if content_format == 'carousel' else '圖片＋影片' if content_format == 'mixed_carousel' else 'Reel' if content_format == 'reel' else '圖片')}內容提案",
        caption=(
            f"想更了解「{goal.title}」嗎？\n\n"
            f"{excerpt}\n\n"
            "歡迎查看活動資訊並完成報名。"
        )[:2_200],
        hashtags=["NTUMaker", "創客"],
        image_requirements=( [] if content_format == "reel" else [
            "第 1 張：5:4（例如 1350×1080）封面，呈現活動主題與清楚的行動呼籲。",
            "第 2 張：5:4（例如 1350×1080）學生或參與者的實作成果，呼應 Strategy 的內容方向。",
            "第 3 張：5:4（例如 1350×1080）活動流程、可獲得的體驗或報名方式。",
        ] if content_format == "carousel" else [
            "單張：5:4（例如 1350×1080）主視覺，呈現活動主題、實作成果與清楚的行動呼籲。"
        ] ),
        video_requirements=(
            ["一支 9:16 直式短影音，呈現活動亮點與行動呼籲。"]
            if content_format == "reel" else
            ["一支短影音，呈現學生實作過程或活動現場互動。"]
            if content_format == "mixed_carousel" else []
        ),
        image_urls=[],
        video_urls=[],
        carousel=content_format in {"carousel", "mixed_carousel"},
        scheduled_at=scheduled_at,
        schedule_requested=schedule_requested,
    )


def generate_content_draft(
    *,
    goal: Goal,
    strategy: Strategy,
    provider: str,
    model_name: str,
    content_format: str = "carousel",
    scheduled_at: datetime | None = None,
    schedule_requested: bool = False,
) -> ContentDraftCreate:
    """Return validated platform data; image URLs are never invented by a model."""
    if provider == "local":
        return _local_draft(
            goal=goal,
            strategy=strategy,
            content_format=content_format,
            scheduled_at=scheduled_at,
            schedule_requested=schedule_requested,
        )

    model = _model_for(provider, model_name)
    prompt = {
        "goal": {"title": goal.title, "description": goal.description, "constraints": goal.constraints},
        "strategy": {"id": strategy.id, "version": strategy.version, "content": strategy.content, "rationale": strategy.rationale},
        "task": "產生一份 Instagram 內容草稿。",
        "rules": [
            "只使用提供的 Goal 與 Strategy，不可編造活動日期、地點、價格、成果或數字。",
            "以繁體中文輸出。",
            "只輸出 JSON object，欄位必須是 title、caption、hashtags、image_requirements、video_requirements、carousel。",
            "title 是 8 至 60 字的繁體中文提案名稱，用來區分不同內容提案。",
            "caption 不含 hashtag；hashtags 是不含 # 的字串陣列；image_requirements 與 video_requirements 都是素材需求字串陣列。",
            "caption 請使用五段式骨架：有辨識度的標題、2 至 3 行內的開頭、約 3 個具體亮點、降低門檻的社群互動段、最後的活動資訊或 CTA。沒有提供的時間、地點、連結不得自行補上。",
            "caption 使用短句、適當斷行與少量 Emoji。開頭應從本次活動的具體物件、技術操作、現場情境或受眾痛點切入；避免『精彩』『豐富』『不容錯過』等空洞形容詞。",
            "每個亮點都需包含具體名詞或動作，例如機具、零件、程式、實作步驟、作品觸感或現場互動；工程幽默必須源自真實的除錯、卡關或物理限制。",
            "只保留一個 CTA，不要同時要求報名、追蹤、私訊、來現場等多個動作。hashtags 建議 3 至 8 個，需與本次活動直接相關且不含 #。",
            "每一項圖片素材需求都必須標示 5:4 比例（例如 1350×1080），並描述畫面主體、現場細節與該張圖的目的。",
            "影音素材需求需說明畫面內容、建議節奏或鏡頭重點；Reel 優先規劃 9:16 直式畫面。不要假設或輸出實際拍攝檔案網址。",
            "不可輸出 image_urls、token、帳號資訊或發布指令。",
            (
                "這是多張圖片貼文，carousel 必須為 true，且 image_requirements 必須列出至少兩張圖片的分頁需求。"
                if content_format == "carousel"
                else "這是圖片＋影片貼文，carousel 必須為 true；image_requirements 與 video_requirements 都要列出需求。"
                if content_format == "mixed_carousel"
                else "這是 Reel，carousel 必須為 false；video_requirements 必須列出單一影片需求。"
                if content_format == "reel"
                else "這是單張貼文，carousel 必須為 false，且 image_requirements 只能描述一張主視覺。"
            ),
        ],
    }
    from langchain_core.messages import HumanMessage, SystemMessage

    response = model.invoke([
        SystemMessage(content=CONTENT_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
    ])
    generated = _json_object(_text_content(response.content))
    generated.pop("image_urls", None)
    generated.pop("video_urls", None)
    generated["channel"] = "instagram"
    generated["post_format"] = "reel" if content_format == "reel" else "mixed_carousel" if content_format == "mixed_carousel" else "image"
    generated.setdefault(
        "title",
        f"{goal.title}：{('多張圖片' if content_format == 'carousel' else '圖片＋影片' if content_format == 'mixed_carousel' else 'Reel' if content_format == 'reel' else '圖片')}內容提案",
    )
    generated["carousel"] = content_format in {"carousel", "mixed_carousel"}
    generated["scheduled_at"] = scheduled_at
    generated["schedule_requested"] = schedule_requested
    try:
        return ContentDraftCreate.model_validate(generated)
    except Exception as exc:
        raise ContentDraftGenerationError("Content model output did not match the draft contract") from exc
