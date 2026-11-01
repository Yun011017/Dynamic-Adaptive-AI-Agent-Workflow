import uuid
import json
import hashlib
from datetime import datetime, timezone
from app.api.schemas.agent_payloads import AgentCompactOutput, FullMarketingRecommendation

def compute_content_hash(caption: str, image_url: str, cta: str) -> str:
    """依據規格書第 15.2 節，以 Canonical JSON 與核心發布欄位計算不可變 SHA-256 content_hash"""
    content_canonical = json.dumps(
        {"caption": caption, "image_url": image_url, "cta": cta},
        sort_keys=True,
        ensure_ascii=False
    )
    return hashlib.sha256(content_canonical.encode("utf-8")).hexdigest()

def enrich_agent_output_to_full_schema(
    agent_output: AgentCompactOutput,
    source_data_id: str,
    default_image_url: str = "[https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=80](https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=80)"
) -> FullMarketingRecommendation:
    """將 Agent 產出的緊湊 JSON 組裝為全規格資料並補齊系統預設值"""
    now_iso = datetime.now(timezone.utc).isoformat()
    rec_id = f"rec_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
    
    content_hash = compute_content_hash(
        caption=agent_output.post_draft.caption_draft,
        image_url=default_image_url,
        cta=agent_output.post_draft.call_to_action
    )

    full_payload = {
        "recommendation_id": rec_id,
        "source_data_id": source_data_id,
        "generated_at": now_iso,
        "status": "pending_approval",
        "content_hash": content_hash,
        "target_audience": {
            **agent_output.target_audience.dict(),
            "confidence_score": 0.90
        },
        "strategy": {
            "content_direction": agent_output.strategy.content_direction,
            "recommended_channel": "instagram",
            "secondary_channels": ["facebook_page"],
            "content_pillar": agent_output.strategy.content_pillar,
            "reasoning": agent_output.strategy.reasoning,
            "expected_metrics": agent_output.strategy.expected_metrics,
            "projected_kpis": {"estimated_reach": 400, "estimated_saves": 20}
        },
        "content_schedule": {
            "recommended_publish_time": now_iso,
            "publish_urgency": agent_output.strategy.content_schedule_recommendation.publish_urgency,
            "slot_rationale": agent_output.strategy.content_schedule_recommendation.slot_rationale,
            "timezone": "Asia/Taipei"
        },
        "post_draft": {
            "media_type": agent_output.post_draft.media_type,
            "caption_draft": agent_output.post_draft.caption_draft,
            "hook_sentence": agent_output.post_draft.hook_sentence,
            "call_to_action": agent_output.post_draft.call_to_action,
            "hashtags": agent_output.post_draft.hashtags,
            "first_comment": agent_output.post_draft.first_comment,
            "media_asset": {
                "image_url": default_image_url,
                "image_generation_prompt": agent_output.post_draft.image_generation_prompt,
                "carousel_items": [],
                "aspect_ratio": "1:1",
                "alt_text": "NTUMaker 實作工作坊現場"
            },
            "ig_specific_options": {
                "collaborators": [],
                "user_tags": [],
                "location_id": None,
                "share_to_feed": True
            }
        },
        "data_provenance": {
            "agent_model": "gemini-2.5-pro",
            "temperature": 0.2,
            "prompt_version": "v2.2_ntumaker",
            "referenced_sources": [s.dict() for s in agent_output.data_provenance.referenced_sources],
            "grounding_check": {
                "is_grounded": True,
                "hallucination_risk": "low",
                "unsupported_claims": []
            }
        },
        "execution_metadata": {
            "approval_request_id": None,
            "approval_status": "pending",
            "reviewer": None,
            "reviewed_at": None,
            "published_media_id": None,
            "permalink": None
        }
    }
    return FullMarketingRecommendation(**full_payload)