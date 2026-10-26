import hmac
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
from .db import engine, get_db
from .models import AgentRun, Execution, Goal, Strategy, Workspace
from .retry import read_with_retry
from .schemas import AgentRunCreate, AgentRunRead, ExecutionRead, GoalCreate, GoalRead, StrategyCreate, StrategyRead

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


@app.post("/agent/runs", response_model=AgentRunRead, status_code=202)
def create_agent_run(data: AgentRunCreate, db: DB, tenant: Tenant):
    """Queue an Agent run for a separate worker; HTTP never waits for model work."""
    input_payload = data.model_dump()
    row = AgentRun(
        workspace_id=tenant,
        run_id=str(uuid.uuid4()),
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
