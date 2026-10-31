from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

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


class AgentRunCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=4_000)
    data_source: Literal["neon_form_summary"] = "neon_form_summary"
    constraints: dict = Field(default_factory=dict)


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: str
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
