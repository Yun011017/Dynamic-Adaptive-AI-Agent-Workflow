from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

# -------------------------------------------------------------
# 1. Agent 模型專注輸出的輕量結構 (Compact Output)
# -------------------------------------------------------------
class TargetAudienceCompact(BaseModel):
    segment_name: str = Field(..., description="受眾族群簡稱")
    persona_summary: str = Field(..., description="受眾特質與心理狀態描繪")
    core_pain_points: List[str] = Field(..., min_items=1, description="受眾痛點清單")

class ScheduleRecommendation(BaseModel):
    slot_rationale: str = Field(..., description="發布時段邏輯")
    publish_urgency: Literal["low", "medium", "high"] = Field(..., description="排程急迫度")

class StrategyCompact(BaseModel):
    content_direction: str = Field(..., description="貼文核心切角與定調")
    content_pillar: Literal["educational", "promotional", "engagement", "social_proof"] = Field(..., description="內容定位")
    reasoning: str = Field(..., description="為何此策略符合輸入資料之因果推論")
    expected_metrics: List[str] = Field(..., description="預期成效指標")
    content_schedule_recommendation: ScheduleRecommendation

class PostDraftCompact(BaseModel):
    media_type: Literal["IMAGE", "VIDEO", "REELS", "CAROUSEL"] = "IMAGE"
    hook_sentence: str = Field(..., description="前兩句吸睛斷句")
    caption_draft: str = Field(..., description="完整 IG 貼文文案")
    call_to_action: str = Field(..., description="單一且具體的行動呼籲字句")
    hashtags: List[str] = Field(..., min_items=3, max_items=8, description="標籤清單")
    first_comment: Optional[str] = Field(None, description="置頂留言")
    image_generation_prompt: str = Field(..., description="AI 生圖 Prompt")

class ReferencedSource(BaseModel):
    source_type: str
    quoted_finding: str

class DataProvenanceCompact(BaseModel):
    referenced_sources: List[ReferencedSource]

class AgentCompactOutput(BaseModel):
    target_audience: TargetAudienceCompact
    strategy: StrategyCompact
    post_draft: PostDraftCompact
    data_provenance: DataProvenanceCompact


# -------------------------------------------------------------
# 2. FastAPI 後端組裝後的完整資料規格 (Full Recommendation Schema)
# -------------------------------------------------------------
class MediaAsset(BaseModel):
    image_url: str
    image_generation_prompt: str
    carousel_items: List[str] = []
    aspect_ratio: str = "1:1"
    alt_text: str

class IGSpecificOptions(BaseModel):
    collaborators: List[str] = []
    user_tags: List[Dict[str, Any]] = []
    location_id: Optional[str] = None
    share_to_feed: bool = True

class PostDraftFull(BaseModel):
    media_type: str
    caption_draft: str
    hook_sentence: str
    call_to_action: str
    hashtags: List[str]
    first_comment: Optional[str]
    media_asset: MediaAsset
    ig_specific_options: IGSpecificOptions

class ExecutionMetadata(BaseModel):
    approval_request_id: Optional[int] = None
    approval_status: str = "pending"
    reviewer: Optional[str] = None
    reviewed_at: Optional[str] = None
    published_media_id: Optional[str] = None
    permalink: Optional[str] = None

class FullMarketingRecommendation(BaseModel):
    recommendation_id: str
    source_data_id: str
    generated_at: str
    status: str
    content_hash: str
    target_audience: Dict[str, Any]
    strategy: Dict[str, Any]
    content_schedule: Dict[str, Any]
    post_draft: PostDraftFull
    data_provenance: Dict[str, Any]
    execution_metadata: ExecutionMetadata


# -------------------------------------------------------------
# 3. 評分回饋規格 (Evaluation Feedback Schema)
# -------------------------------------------------------------
class DeductionItem(BaseModel):
    deduction_id: str
    category: Literal["tone_and_voice", "cta_compliance", "fact_accuracy", "formatting", "visual_and_prompt", "actionability"]
    points: float
    target_field: str
    issue_description: str
    suggestion: str

class HumanEvaluation(BaseModel):
    reviewer: str
    reviewed_at: str
    status: Literal["approved", "rejected", "needs_revision"]
    base_score: float = 100.0
    total_deduction: float
    total_score: float
    is_override_automated: bool = False
    override_reason: Optional[str] = None
    deductions: List[DeductionItem] = []
    qualitative_notes: Dict[str, Any]

class ContentEvaluationFeedback(BaseModel):
    evaluation_id: str
    recommendation_id: str
    evaluated_at: str
    evaluator_mode: Literal["automated_only", "human_only", "hybrid"] = "hybrid"
    final_verdict: Literal["approved", "rejected", "needs_revision"]
    is_publishable: bool
    summary: Dict[str, Any]
    automated_scores: Optional[Dict[str, Any]] = None
    human_evaluation: Optional[HumanEvaluation] = None