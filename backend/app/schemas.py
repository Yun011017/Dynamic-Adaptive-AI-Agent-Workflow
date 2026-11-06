from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    kpi_definition: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)

class GoalRead(GoalCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    status: str
    created_at: datetime

class StrategyCreate(BaseModel):
    version: int = Field(gt=0)
    content: str = Field(min_length=1)
    rationale: str | None = None

class StrategyRead(StrategyCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    goal_id: int
    created_at: datetime

class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    strategy_id: int
    status: str
    result_summary: str | None
    created_at: datetime


class ContentDraftCreate(BaseModel):
    """Platform-owned content draft. Provider credentials never appear here."""

    channel: Literal["instagram"] = "instagram"
    title: str = Field(default="未命名內容提案", min_length=1, max_length=160)
    caption: str = Field(min_length=1, max_length=2_200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    image_requirements: list[str] = Field(default_factory=list, max_length=12)
    image_urls: list[str] = Field(default_factory=list, max_length=10)
    carousel: bool = False
    scheduled_at: datetime | None = None
    schedule_requested: bool = False

    @field_validator("hashtags")
    @classmethod
    def normalize_hashtags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            tag = value.strip().lstrip("#").replace(" ", "")
            if not tag or len(tag) > 100:
                raise ValueError("Each hashtag must contain 1 to 100 non-space characters")
            if tag not in cleaned:
                cleaned.append(tag)
        return cleaned

    @field_validator("image_requirements")
    @classmethod
    def clean_image_requirements(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 500 for value in cleaned):
            raise ValueError("An image requirement must not exceed 500 characters")
        return cleaned

    @field_validator("image_urls")
    @classmethod
    def validate_image_urls(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            url = value.strip()
            if not url.startswith("https://"):
                raise ValueError("Image URLs must use public HTTPS")
            if url not in cleaned:
                cleaned.append(url)
        return cleaned

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone_for_schedule(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("A scheduled time must include a timezone")
        if value is not None and value <= datetime.now(timezone.utc):
            raise ValueError("A scheduled time must be in the future")
        return value

    @model_validator(mode="after")
    def validate_carousel_assets(self):
        if self.schedule_requested and self.scheduled_at is None:
            raise ValueError("A scheduled draft needs a scheduled time")
        if self.carousel and len(self.image_requirements) < 2:
            raise ValueError("A carousel needs at least two image requirements")
        if self.carousel and self.image_urls and len(self.image_urls) < 2:
            raise ValueError("A carousel needs at least two public image URLs when URLs are supplied")
        return self


class ContentDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    execution_id: int
    tool: str
    operation: str
    status: str
    draft_version: int
    content_hash: str
    payload: dict
    idempotency_key: str
    external_id: str | None
    created_at: datetime


class ContentDraftGenerateRequest(BaseModel):
    """Request a worker-owned draft generation; the HTTP request never invokes a model."""

    channel: Literal["instagram"] = "instagram"
    content_format: Literal["carousel", "single"] = "carousel"
    scheduled_at: datetime | None = None
    schedule_requested: bool = False

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone_for_schedule(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("A scheduled time must include a timezone")
        if value is not None and value <= datetime.now(timezone.utc):
            raise ValueError("A scheduled time must be in the future")
        return value

    @model_validator(mode="after")
    def require_time_when_scheduling(self):
        if self.schedule_requested and self.scheduled_at is None:
            raise ValueError("A scheduled draft needs a scheduled time")
        return self


class AgentRunCreate(BaseModel):
    goal_id: int = Field(gt=0)
    goal: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=4_000)
    data_source: Literal["neon_form_summary"] = "neon_form_summary"
    constraints: dict = Field(default_factory=dict)


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: str
    goal_id: int | None
    status: str
    input_payload: dict
    output_payload: dict | None
    error_code: str | None
    error_message: str | None
    agent_provider: str
    agent_model: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "needs_revision"]
    reason: str | None = None
    expected_version: int | None = None

class ApprovalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    action_id: int
    draft_version: int
    content_hash: str
    status: str
    decision_reason: str | None
    requested_by: str
    reviewed_by: str | None
    requested_at: datetime
    decided_at: datetime | None
    expires_at: datetime | None
