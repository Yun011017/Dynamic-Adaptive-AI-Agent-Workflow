import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from .config import settings
from .content_draft_jobs import queue_content_draft_run
from .db import engine, get_db
from .content_drafts import create_content_draft, create_content_draft_version
from .evaluation import METRICS, build_evaluation_graph
from .models import AgentRun, AgentRunCheckpoint, Execution, ExecutionAction, Goal, Observation, Strategy, Workspace
from .retry import read_with_retry
from .schemas import AgentRunCreate, AgentRunRead, ApprovedScheduleUpdate, ContentDraftCreate, ContentDraftGenerateRequest, ContentDraftRead, ExecutionRead, GoalCreate, GoalRead, StrategyCreate, StrategyRead, MediaUploadPresignRequest, MediaUploadPresignRead, UploadedMediaRead
from .services.media_storage import cleanup_expired_media_assets, complete_direct_upload, create_direct_upload, upload_media_via_proxy
from .form_bindings import bind_form_source, list_form_sources
from .schemas import FormBindingCreate
from .schemas import FormSourceCreate, FormSourceUpdate
from .form_sources import create_source, source_read, sync_registered_source
from .models import FormSource
from .form_sync import FormSyncError

app = FastAPI(title="Dynamic Adaptive AI Agent Workflow", version="0.2.0")
evaluation_graph = build_evaluation_graph()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()],
    # Next.js may select a different local port when 3000 is already occupied.
    # Production origins remain explicitly controlled by FRONTEND_ORIGINS.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
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


def scoped(db, model, object_id, workspace_id, *, lock=False):
    query = select(model).where(model.id == object_id, model.workspace_id == workspace_id)
    if lock:
        query = query.with_for_update(nowait=True)
    try:
        value = read_with_retry(lambda: db.scalar(query), reset=db.rollback)
    except OperationalError as exc:
        if lock and getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(409, "Publishing is already in progress") from exc
        raise
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


@app.post("/media/uploads/presign", response_model=MediaUploadPresignRead, status_code=201)
def presign_media_upload(data: MediaUploadPresignRequest, db: DB, tenant: Tenant):
    """Create a direct browser-to-R2 upload form without proxying media through Vercel."""
    return create_direct_upload(db=db, workspace_id=tenant, **data.model_dump())


@app.post("/media/uploads/{asset_id}/complete", response_model=UploadedMediaRead)
def complete_media_upload(asset_id: int, db: DB, tenant: Tenant):
    return complete_direct_upload(db=db, workspace_id=tenant, asset_id=asset_id)


@app.post("/media/uploads", response_model=UploadedMediaRead, status_code=201)
def upload_small_media_fallback(
    file: Annotated[UploadFile, File(...)],
    media_type: Literal["image", "video"],
    tenant: Tenant,
):
    return upload_media_via_proxy(file=file, workspace_id=tenant, media_type=media_type)


@app.get("/internal/media/cleanup")
def cleanup_media_uploads(request: Request, db: DB):
    """Vercel Cron invokes this daily to remove uploads not saved into a proposal."""
    if not settings.cron_secret:
        raise HTTPException(503, "Media cleanup is not configured")
    authorization = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.cron_secret.get_secret_value()}"
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Authentication required")
    deleted = cleanup_expired_media_assets(db=db)
    db.commit()
    return {"deleted": deleted}


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


@app.get('/strategies/{strategy_id}/executions', response_model=list[ExecutionRead])
def list_strategy_executions(strategy_id: int, db: DB, tenant: Tenant):
    scoped(db, Strategy, strategy_id, tenant)
    return db.scalars(select(Execution).where(Execution.workspace_id == tenant,
                                            Execution.strategy_id == strategy_id).order_by(Execution.id.desc())).all()


@app.get('/form-sources')
def get_form_sources(db: DB, tenant: Tenant):
    return list_form_sources(db, tenant)


@app.get('/form-source-configs')
def get_form_source_configs(db: DB, tenant: Tenant):
    return [source_read(row) for row in db.scalars(select(FormSource).where(
        FormSource.workspace_id == tenant).order_by(FormSource.id.desc()))]


@app.post('/form-source-configs', status_code=201)
def add_form_source(data: FormSourceCreate, db: DB, tenant: Tenant):
    row = create_source(db, tenant, data)
    result = source_read(row)
    db.commit()
    return result


@app.patch('/form-source-configs/{source_pk}')
def update_form_source(source_pk: int, data: FormSourceUpdate, db: DB, tenant: Tenant):
    db.scalar(select(Workspace.id).where(Workspace.id == tenant).with_for_update())
    row = scoped(db, FormSource, source_pk, tenant)
    row.enabled = data.enabled
    result = source_read(row)
    db.commit()
    return result


@app.post('/form-source-configs/{source_pk}/sync')
def sync_form_source(source_pk: int, db: DB, tenant: Tenant):
    # End the authentication read transaction before network I/O.
    db.rollback()
    try:
        return sync_registered_source(source_pk, tenant)
    except FormSyncError as error:
        raise HTTPException(502, str(error)) from None


@app.post('/executions/{execution_id}/form-bindings')
def create_form_binding(execution_id: int, data: FormBindingCreate, db: DB, tenant: Tenant):
    result = bind_form_source(db, tenant, execution_id, data.source_id, data.copy_source)
    db.commit()
    return result


@app.get("/executions/{execution_id}/evaluation")
def get_execution_evaluation(execution_id: int, db: DB, tenant: Tenant):
    execution = scoped(db, Execution, execution_id, tenant)
    strategy = scoped(db, Strategy, execution.strategy_id, tenant)
    goal = scoped(db, Goal, strategy.goal_id, tenant)
    metric_names = [name for aliases in METRICS.values() for name in aliases]
    observations = read_with_retry(
        lambda: db.scalars(
            select(Observation)
            .where(
                Observation.workspace_id == tenant,
                Observation.execution_id == execution_id,
                Observation.strategy_id == strategy.id,
                Observation.metric.in_(metric_names),
            )
            .order_by(Observation.observed_at.desc(), Observation.id.desc())
        ).all(),
        reset=db.rollback,
    )
    result = evaluation_graph.invoke({
        "targets": goal.kpi_definition,
        "strategy_context": {
            "goal": goal.title,
            "version": strategy.version,
            "content": strategy.content,
        },
        "observations": [{
            "id": row.id,
            "metric": row.metric,
            "value": row.value,
            "external_event_id": row.external_event_id,
            "observed_at": row.observed_at.isoformat(),
            "attribution_status": row.attribution_status,
        } for row in observations],
    })
    return {
        "goal_id": goal.id,
        "strategy_id": strategy.id,
        "execution_id": execution_id,
        **result["evaluation"],
    }


@app.post("/executions/{execution_id}/evaluation")
def save_execution_evaluation(execution_id: int, db: DB, tenant: Tenant):
    execution = db.scalar(
        select(Execution)
        .where(Execution.id == execution_id, Execution.workspace_id == tenant)
        .with_for_update()
    )
    if execution is None:
        raise HTTPException(404, "Resource not found")
    result = get_execution_evaluation(execution_id, db, tenant)
    result["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    execution.evaluation_result = result
    db.commit()
    return result


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


@app.patch("/content-drafts/{action_id}/schedule", response_model=ContentDraftRead)
def reschedule_approved_draft(action_id: int, data: ApprovedScheduleUpdate, db: DB, tenant: Tenant):
    """Change only the scheduled time after approval; content changes need a new review."""
    action = scoped(db, ExecutionAction, action_id, tenant, lock=True)
    approval = db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.workspace_id == tenant,
            ApprovalRequest.action_id == action.id,
            ApprovalRequest.draft_version == action.draft_version,
            ApprovalRequest.content_hash == action.content_hash,
            ApprovalRequest.status == "APPROVED",
        )
        .order_by(ApprovalRequest.decided_at.desc(), ApprovalRequest.id.desc())
    )
    if approval is None:
        raise HTTPException(409, "此提案沒有可沿用的核准紀錄；請修改後重新送審")
    row = ApprovalService.reschedule_approved_action(
        db,
        action=action,
        approval=approval,
        scheduled_at=data.scheduled_at,
    )
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


@app.delete("/agent/runs/{run_id}", status_code=204)
def delete_agent_run(run_id: str, db: DB, tenant: Tenant):
    """Remove one history record without deleting its saved Strategy or drafts."""
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
    if row.status in {"PENDING", "RUNNING"}:
        raise HTTPException(409, "A running work record cannot be deleted")
    db.query(AgentRunCheckpoint).filter(
        AgentRunCheckpoint.workspace_id == tenant,
        AgentRunCheckpoint.agent_run_id == row.id,
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()


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
    input_payload = dict(run.input_payload)
    input_payload["goal_id"] = goal.id
    run.input_payload = input_payload

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
    signup_url = output.get("constraints", {}).get("signup_url") if isinstance(output.get("constraints"), dict) else None
    if signup_url:
        strategy_fields["signup_url"] = signup_url
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
from app.schemas import ApprovalDecisionRequest, ApprovalRequestRead, PublishActionRequest
from app.services.approval_service import ApprovalService
from app.services.publisher_service import InstagramPublisherService

@app.post("/actions/{action_id}/approval-requests", response_model=ApprovalRequestRead, status_code=201)
def submit_action_for_review(action_id: int, db: DB, tenant: Tenant):
    action = scoped(db, ExecutionAction, action_id, tenant)
    approval = ApprovalService.submit_for_review(db, action=action)
    db.commit()
    db.refresh(approval)
    return ApprovalRequestRead.model_validate(approval).model_copy(
        update={"action_payload": action.payload}
    )

@app.get("/approval-requests", response_model=list[ApprovalRequestRead])
def list_approval_requests(db: DB, tenant: Tenant, status: str = "PENDING_REVIEW"):
    rows = read_with_retry(
        lambda: db.execute(
            select(ApprovalRequest, ExecutionAction.payload, Goal.title)
            .select_from(ApprovalRequest)
            .join(
                ExecutionAction,
                (ExecutionAction.workspace_id == ApprovalRequest.workspace_id)
                & (ExecutionAction.id == ApprovalRequest.action_id),
            )
            .join(
                Execution,
                (Execution.id == ExecutionAction.execution_id)
                & (Execution.workspace_id == ExecutionAction.workspace_id),
            )
            .join(
                Strategy,
                (Strategy.id == Execution.strategy_id)
                & (Strategy.workspace_id == Execution.workspace_id),
            )
            .join(
                Goal,
                (Goal.id == Strategy.goal_id)
                & (Goal.workspace_id == Strategy.workspace_id),
            )
            .where(ApprovalRequest.workspace_id == tenant, ApprovalRequest.status == status)
            .order_by(ApprovalRequest.requested_at.desc())
        ).all(),
        reset=db.rollback,
    )
    return [
        ApprovalRequestRead.model_validate(approval).model_copy(
            update={"action_payload": payload, "campaign_name": campaign_name}
        )
        for approval, payload, campaign_name in rows
    ]

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
    return ApprovalRequestRead.model_validate(updated_approval).model_copy(
        update={"action_payload": action.payload}
    )

@app.post("/actions/{action_id}/execute")
async def execute_action(action_id: int, db: DB, tenant: Tenant, data: PublishActionRequest | None = None):
    # Serialize manual publishing with the scheduled worker's row lock.
    action = scoped(db, ExecutionAction, action_id, tenant, lock=True)
    if action.status != "SCHEDULED":
        raise HTTPException(409, "Only approved scheduled content can be published")
    scheduled_at = action.payload.get("scheduled_at")
    if not scheduled_at:
        raise HTTPException(409, "Scheduled content is missing its publish time")
    try:
        publish_at = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "Scheduled publish time is invalid") from exc
    if publish_at > datetime.now(timezone.utc):
        raise HTTPException(409, "This content is not due for publishing yet")
    if data and data.video_url is not None:
        media = action.payload.get("meta_adapter_payload") or {}
        if media.get("media_type") != "REELS" or media.get("video_url") != data.video_url:
            raise HTTPException(409, "video_url must match the approved Reel")
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
