import hmac
import json
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .config import settings
from .content_draft_jobs import queue_content_draft_run
from .db import engine, get_db
from .content_drafts import create_content_draft, create_content_draft_version
from .models import AgentRun, Execution, ExecutionAction, Goal, Strategy, Workspace
from .retry import read_with_retry
from .schemas import AgentRunCreate, AgentRunRead, ContentDraftCreate, ContentDraftGenerateRequest, ContentDraftRead, ExecutionRead, GoalCreate, GoalRead, StrategyCreate, StrategyRead

app = FastAPI(title="Dynamic Adaptive AI Agent Workflow", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()],
    # Next.js may select a different local port when 3000 is already occupied.
    # Production origins remain explicitly controlled by FRONTEND_ORIGINS.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    conflict = isinstance(exc, IntegrityError)
    return JSONResponse(status_code=409 if conflict else 503, content={"error": {
        "code": "DATA_CONFLICT" if conflict else "DATABASE_UNAVAILABLE",
        "message": "Data conflicts with existing records" if conflict else "Database temporarily unavailable",
        "request_id": getattr(request.state, "request_id", None),
    }})


def workspace(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> int:
    # Temporary development-only gate, NOT a replacement for the OIDC/RBAC owner.
    if not settings.platform_api_key:
        raise HTTPException(503, "Development API access is disabled")
    if not credentials or not hmac.compare_digest(credentials.credentials, settings.platform_api_key):
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    tenant = read_with_retry(
        lambda: db.scalar(select(Workspace).where(Workspace.slug == settings.platform_workspace_slug, Workspace.status == "active")),
        reset=db.rollback,
    )
    if tenant is None:
        raise HTTPException(503, "Configured development workspace is unavailable")
    return tenant.id


Tenant = Annotated[int, Depends(workspace)]


def scoped(db, model, object_id, workspace_id):
    value = read_with_retry(
        lambda: db.scalar(select(model).where(model.id == object_id, model.workspace_id == workspace_id)),
        reset=db.rollback,
    )
    if value is None:
        raise HTTPException(404, "Resource not found")
    return value


@app.get("/health")
def health():
    def probe():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    # Health probes are bounded to connect_timeout; callers may retry later.
    probe()
    return {"status": "ok", "database": "connected"}


@app.post("/goals", response_model=GoalRead, status_code=201)
def create_goal(data: GoalCreate, db: DB, tenant: Tenant):
    goal = Goal(workspace_id=tenant, **data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@app.get("/goals", response_model=list[GoalRead])
def list_goals(db: DB, tenant: Tenant, limit: int = 50, offset: int = 0):
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    return read_with_retry(
        lambda: db.scalars(select(Goal).where(Goal.workspace_id == tenant).order_by(Goal.id).limit(limit).offset(offset)).all(),
        reset=db.rollback,
    )


@app.get("/goals/{goal_id}", response_model=GoalRead)
def get_goal(goal_id: int, db: DB, tenant: Tenant):
    return scoped(db, Goal, goal_id, tenant)


@app.post("/goals/{goal_id}/strategies", response_model=StrategyRead, status_code=201)
def create_strategy(goal_id: int, data: StrategyCreate, db: DB, tenant: Tenant):
    scoped(db, Goal, goal_id, tenant)
    row = Strategy(workspace_id=tenant, goal_id=goal_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.get("/strategies", response_model=list[StrategyRead])
def list_strategies(db: DB, tenant: Tenant, limit: int = 50):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid limit")
    return read_with_retry(
        lambda: db.scalars(
            select(Strategy)
            .where(Strategy.workspace_id == tenant)
            .order_by(Strategy.created_at.desc(), Strategy.id.desc())
            .limit(limit)
        ).all(),
        reset=db.rollback,
    )


@app.post("/strategies/{strategy_id}/executions", response_model=ExecutionRead, status_code=201)
def create_execution_record(strategy_id: int, db: DB, tenant: Tenant):
    # Record only: no Agent scheduling and no external side effects.
    scoped(db, Strategy, strategy_id, tenant)
    row = Execution(workspace_id=tenant, strategy_id=strategy_id, status="QUEUED")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.get("/executions/{execution_id}", response_model=ExecutionRead)
def get_execution(execution_id: int, db: DB, tenant: Tenant):
    return scoped(db, Execution, execution_id, tenant)


@app.post("/strategies/{strategy_id}/content-drafts", response_model=ContentDraftRead, status_code=201)
def create_draft(strategy_id: int, data: ContentDraftCreate, db: DB, tenant: Tenant):
    strategy = scoped(db, Strategy, strategy_id, tenant)
    row, _created = create_content_draft(db, strategy=strategy, data=data)
    db.commit()
    db.refresh(row)
    return row


@app.get("/strategies/{strategy_id}/content-drafts", response_model=list[ContentDraftRead])
def list_drafts(strategy_id: int, db: DB, tenant: Tenant, limit: int = 50):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid limit")
    scoped(db, Strategy, strategy_id, tenant)
    return read_with_retry(
        lambda: db.scalars(
            select(ExecutionAction)
            .join(Execution, Execution.id == ExecutionAction.execution_id)
            .where(
                ExecutionAction.workspace_id == tenant,
                Execution.workspace_id == tenant,
                Execution.strategy_id == strategy_id,
            )
            .order_by(ExecutionAction.created_at.desc(), ExecutionAction.id.desc())
            .limit(limit)
        ).all(),
        reset=db.rollback,
    )


@app.get("/content-drafts/scheduled", response_model=list[ContentDraftRead])
def list_scheduled_drafts(db: DB, tenant: Tenant, limit: int = 100):
    """Return one workspace-wide queue of explicitly scheduled content drafts."""
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid limit")
    return read_with_retry(
        lambda: db.scalars(
            select(ExecutionAction)
            .where(
                ExecutionAction.workspace_id == tenant,
                ExecutionAction.status == "SCHEDULED",
            )
            .order_by(ExecutionAction.created_at.desc(), ExecutionAction.id.desc())
            .limit(limit)
        ).all(),
        reset=db.rollback,
    )


@app.post("/strategies/{strategy_id}/content-draft-runs", response_model=AgentRunRead, status_code=202)
def queue_content_draft(strategy_id: int, data: ContentDraftGenerateRequest, db: DB, tenant: Tenant):
    """Queue model work; the background worker creates the persisted content draft."""
    strategy = scoped(db, Strategy, strategy_id, tenant)
    row = queue_content_draft_run(
        db,
        workspace_id=tenant,
        strategy_id=strategy.id,
        provider=settings.agent_provider,
        model_name=settings.agent_model,
        content_format=data.content_format,
        scheduled_at=data.scheduled_at,
        schedule_requested=data.schedule_requested,
    )
    db.commit()
    db.refresh(row)
    return row


@app.post("/content-drafts/{action_id}/versions", response_model=ContentDraftRead, status_code=201)
def revise_draft(action_id: int, data: ContentDraftCreate, db: DB, tenant: Tenant):
    previous = scoped(db, ExecutionAction, action_id, tenant)
    if previous.status in {"EXECUTING", "SUCCEEDED"}:
        raise HTTPException(409, "A published or executing draft cannot be revised")
    execution = scoped(db, Execution, previous.execution_id, tenant)
    strategy = scoped(db, Strategy, execution.strategy_id, tenant)
    row = create_content_draft_version(db, previous=previous, strategy=strategy, data=data)
    db.commit()
    db.refresh(row)
    return row


@app.post("/agent/runs", response_model=AgentRunRead, status_code=202)
def create_agent_run(data: AgentRunCreate, db: DB, tenant: Tenant):
    """Queue an Agent run for a separate worker; HTTP never waits for model work."""
    scoped(db, Goal, data.goal_id, tenant)
    input_payload = data.model_dump()
    row = AgentRun(
        workspace_id=tenant,
        run_id=str(uuid.uuid4()),
        goal_id=data.goal_id,
        status="PENDING",
        input_payload=input_payload,
        agent_provider=settings.agent_provider,
        agent_model=settings.agent_model,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.get("/agent/runs", response_model=list[AgentRunRead])
def list_agent_runs(db: DB, tenant: Tenant, limit: int = 50):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid limit")
    return read_with_retry(
        lambda: db.scalars(
            select(AgentRun)
            .where(AgentRun.workspace_id == tenant)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        ).all(),
        reset=db.rollback,
    )


@app.get("/agent/runs/{run_id}", response_model=AgentRunRead)
def get_agent_run(run_id: str, db: DB, tenant: Tenant):
    row = read_with_retry(
        lambda: db.scalar(
            select(AgentRun).where(
                AgentRun.run_id == run_id, AgentRun.workspace_id == tenant
            )
        ),
        reset=db.rollback,
    )
    if row is None:
        raise HTTPException(404, "Agent run not found")
    return row


@app.post("/agent/runs/{run_id}/strategies", response_model=AgentRunRead)
def save_legacy_run_strategy(run_id: str, db: DB, tenant: Tenant):
    """Backfill a formal Strategy for an older completed analysis run.

    Historical runs may contain useful output but predate goal/strategy links.
    Persist their existing analysis without rerunning the Agent, so it can enter
    the normal content-draft workflow.
    """
    run = read_with_retry(
        lambda: db.scalar(
            select(AgentRun).where(
                AgentRun.run_id == run_id,
                AgentRun.workspace_id == tenant,
            )
        ),
        reset=db.rollback,
    )
    if run is None:
        raise HTTPException(404, "Resource not found")
    if run.status != "COMPLETED" or not run.output_payload:
        raise HTTPException(409, "Only completed analysis runs can create a Strategy")
    if run.input_payload.get("job_type") == "CONTENT_DRAFT":
        raise HTTPException(409, "Content draft runs cannot create a Strategy")

    output = dict(run.output_payload)
    strategy_id = output.get("strategy_id")
    if isinstance(strategy_id, int) and not isinstance(strategy_id, bool):
        strategy = db.scalar(
            select(Strategy).where(
                Strategy.id == strategy_id,
                Strategy.workspace_id == tenant,
            )
        )
        if strategy is not None:
            return run

    goal = None
    if run.goal_id is not None:
        goal = db.scalar(
            select(Goal).where(Goal.id == run.goal_id, Goal.workspace_id == tenant)
        )
    goal_title = str(run.input_payload.get("goal") or "歷史策略工作").strip() or "歷史策略工作"
    if goal is None:
        goal = db.scalar(
            select(Goal)
            .where(Goal.workspace_id == tenant, Goal.title == goal_title)
            .order_by(Goal.id.desc())
        )
    if goal is None:
        goal = Goal(
            workspace_id=tenant,
            title=goal_title,
            description=run.input_payload.get("context") or None,
            constraints=run.input_payload.get("constraints") or {},
        )
        db.add(goal)
        db.flush()
    run.goal_id = goal.id

    latest_version = db.scalar(
        select(Strategy.version)
        .where(Strategy.workspace_id == tenant, Strategy.goal_id == goal.id)
        .order_by(Strategy.version.desc())
        .limit(1)
    ) or 0
    strategy_fields = {
        key: output.get(key)
        for key in ("target_audience", "content_direction", "channel", "expected_metrics", "reason")
    }
    strategy_fields["data_source"] = output.get("data_source") or {}
    strategy = Strategy(
        workspace_id=tenant,
        goal_id=goal.id,
        version=latest_version + 1,
        content=json.dumps(strategy_fields, ensure_ascii=False, sort_keys=True),
        rationale=output.get("reason"),
    )
    db.add(strategy)
    db.flush()
    output.update({
        "strategy_id": strategy.id,
        "goal_id": goal.id,
        "strategy_version": strategy.version,
        "strategy": strategy_fields,
    })
    run.output_payload = output
    db.commit()
    db.refresh(run)
    return run

from app.models import ApprovalRequest
from app.schemas import ApprovalDecisionRequest, ApprovalRequestRead
from app.services.approval_service import ApprovalService
from app.services.publisher_service import InstagramPublisherService

@app.post("/actions/{action_id}/approval-requests", response_model=ApprovalRequestRead, status_code=201)
def submit_action_for_review(action_id: int, db: DB, tenant: Tenant):
    action = scoped(db, ExecutionAction, action_id, tenant)
    approval = ApprovalService.submit_for_review(db, action=action)
    db.commit()
    db.refresh(approval)
    return approval

@app.get("/approval-requests", response_model=list[ApprovalRequestRead])
def list_approval_requests(db: DB, tenant: Tenant, status: str = "PENDING_REVIEW"):
    return read_with_retry(
        lambda: db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.workspace_id == tenant, ApprovalRequest.status == status)
            .order_by(ApprovalRequest.requested_at.desc())
        ).all(),
        reset=db.rollback,
    )

@app.post("/approval-requests/{approval_id}/decision", response_model=ApprovalRequestRead)
def decide_approval_request(approval_id: int, data: ApprovalDecisionRequest, db: DB, tenant: Tenant):
    approval = scoped(db, ApprovalRequest, approval_id, tenant)
    action = scoped(db, ExecutionAction, approval.action_id, tenant)
    if data.expected_version and action.draft_version != data.expected_version:
        raise HTTPException(409, "Action draft version mismatch")
    
    updated_approval = ApprovalService.process_decision(
        db,
        approval=approval,
        action=action,
        decision=data.decision,
        reason=data.reason,
    )
    db.commit()
    db.refresh(updated_approval)
    return updated_approval

@app.post("/actions/{action_id}/execute")
async def execute_action(action_id: int, db: DB, tenant: Tenant):
    action = scoped(db, ExecutionAction, action_id, tenant)
    approval = db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.workspace_id == tenant,
            ApprovalRequest.action_id == action.id,
            ApprovalRequest.draft_version == action.draft_version,
        )
        .order_by(ApprovalRequest.id.desc())
    )
    
    # 執行前置檢查與受控發布
    external_id = await InstagramPublisherService.publish_action(db, action, approval)
    return {"message": "發布成功", "action_id": action.id, "external_id": external_id, "status": "SUCCEEDED"}
