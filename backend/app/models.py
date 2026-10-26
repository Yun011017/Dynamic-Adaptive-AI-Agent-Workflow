from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantRow:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Member(TenantRow, Base):
    __tablename__ = "members"
    subject_id: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    __table_args__ = (UniqueConstraint("workspace_id", "subject_id"), CheckConstraint("role IN ('Admin', 'Agent')", name="ck_members_role"))


class Goal(TenantRow, Base):
    __tablename__ = "goals"
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    kpi_definition: Mapped[dict] = mapped_column(JSON, server_default="{}")
    constraints: Mapped[dict] = mapped_column(JSON, server_default="{}")
    __table_args__ = (UniqueConstraint("workspace_id", "id"),)


class Strategy(TenantRow, Base):
    __tablename__ = "strategies"
    goal_id: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "goal_id"], ["goals.workspace_id", "goals.id"]),
        UniqueConstraint("workspace_id", "goal_id", "version"), UniqueConstraint("workspace_id", "id"),
        CheckConstraint("version > 0", name="ck_strategies_version"),
    )


class Execution(TenantRow, Base):
    __tablename__ = "executions"
    strategy_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), server_default="QUEUED")
    result_summary: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "strategy_id"], ["strategies.workspace_id", "strategies.id"]),
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint("status IN ('QUEUED','RUNNING','WAITING_APPROVAL','WAITING_OBSERVATION','SUCCEEDED','FAILED','CANCELLED','MANUAL_REVIEW')", name="ck_executions_status"),
    )


class AgentRun(TenantRow, Base):
    __tablename__ = "agent_runs"
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16), server_default="PENDING")
    input_payload: Mapped[dict] = mapped_column(JSON, server_default="{}")
    output_payload: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    agent_provider: Mapped[str] = mapped_column(String(32), server_default="local")
    agent_model: Mapped[str] = mapped_column(String(128), server_default="deterministic-langgraph")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("run_id"),
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','FAILED')", name="ck_agent_runs_status"),
    )


class ExecutionAction(TenantRow, Base):
    __tablename__ = "execution_actions"
    execution_id: Mapped[int] = mapped_column(BigInteger)
    tool: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="DRAFT")
    draft_version: Mapped[int] = mapped_column(Integer, server_default="1")
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "execution_id"], ["executions.workspace_id", "executions.id"]),
        UniqueConstraint("workspace_id", "idempotency_key"), UniqueConstraint("workspace_id", "id"),
        CheckConstraint("draft_version > 0", name="ck_actions_version"),
        CheckConstraint("status IN ('DRAFT','PENDING_REVIEW','APPROVED','REJECTED','EXPIRED','EXECUTING','SUCCEEDED','FAILED','TIMEOUT','VERIFYING','MANUAL_REVIEW')", name="ck_actions_status"),
    )


class ExternalEvent(TenantRow, Base):
    __tablename__ = "external_events"
    provider: Mapped[str] = mapped_column(String(64))
    source_account: Mapped[str] = mapped_column(String(255))
    source_object_id: Mapped[str] = mapped_column(String(255))
    source_version: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict] = mapped_column(JSON)
    processing_status: Mapped[str] = mapped_column(String(32), server_default="RECEIVED")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "source_account", "source_object_id", "source_version", name="uq_external_event_source"),
        UniqueConstraint("workspace_id", "id"), CheckConstraint("attempts >= 0", name="ck_event_attempts"),
    )


class Observation(TenantRow, Base):
    __tablename__ = "observations"
    external_event_id: Mapped[int] = mapped_column(BigInteger)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    execution_id: Mapped[int | None] = mapped_column(BigInteger)
    metric: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Numeric(20, 6))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attribution_status: Mapped[str] = mapped_column(String(32), server_default="unattributed")
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "external_event_id"], ["external_events.workspace_id", "external_events.id"]),
        ForeignKeyConstraint(["workspace_id", "strategy_id"], ["strategies.workspace_id", "strategies.id"]),
        ForeignKeyConstraint(["workspace_id", "execution_id"], ["executions.workspace_id", "executions.id"]),
        UniqueConstraint("workspace_id", "external_event_id", "metric", "observed_at", name="uq_observation_source_metric"),
    )
