from datetime import datetime
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
