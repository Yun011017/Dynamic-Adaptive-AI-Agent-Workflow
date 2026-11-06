"""Database-backed worker for bounded Agent runs.

Run with ``python -m app.agent_worker`` from ``backend/``. The worker claims
only PENDING records, so multiple workers can poll the same Neon database.
"""
import argparse
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .agent_runner import run_agent
from .content_drafts import create_content_draft
from .content_draft_jobs import queue_content_draft_run
from .content_generator import generate_content_draft
from .form_sync import sync_once
from .config import settings
from .db import SessionLocal
from .models import AgentRun, AgentRunCheckpoint, Goal, Strategy
from .schemas import ContentDraftGenerateRequest

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import ExecutionAction, ApprovalRequest
from app.services.publisher_service import InstagramPublisherService

def process_scheduled_publishing(db: Session) -> str | None:
    """檢查已核准且到達發布時間的 Action，由 worker 執行發布"""
    now = datetime.now(timezone.utc)
    
    # 取出已核准的 action
    actions = db.scalars(
        select(ExecutionAction)
        .where(
            ExecutionAction.status == "APPROVED",
            ExecutionAction.tool == "meta_api",
            ExecutionAction.operation == "instagram_publish"
        )
        .with_for_update(skip_locked=True)
    ).all()

    for action in actions:
        # 若有排程時間，檢查是否已到期
        scheduled_at_str = action.payload.get("scheduled_at")
        if scheduled_at_str:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
            if scheduled_at > now:
                continue  # 時間未到

        # 取得最新對應的 approval
        approval = db.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.workspace_id == action.workspace_id,
                ApprovalRequest.action_id == action.id,
                ApprovalRequest.draft_version == action.draft_version,
            )
            .order_by(ApprovalRequest.id.desc())
        )

        action.status = "EXECUTING"
        db.commit()

        try:
            # 呼叫受控發布
            external_id = asyncio.run(
                InstagramPublisherService.publish_action(db, action, approval)
            )
            return f"Action {action.id} published successfully as {external_id}"
        except Exception as exc:
            action.status = "FAILED"
            db.commit()
            print(f"Action {action.id} publishing failed: {exc}")
            return f"Action {action.id} failed"

    return None

def claim_next_run(db: Session) -> AgentRun | None:
    """Claim a waiting or stale run, skipping another worker's row lock."""
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=settings.agent_run_lease_seconds
    )
    row = db.scalars(
        select(AgentRun)
        .where(or_(
            AgentRun.status == "PENDING",
            (AgentRun.status == "RUNNING") & (AgentRun.started_at < stale_before),
        ))
        .order_by(AgentRun.created_at, AgentRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if row is None:
        return None
    row.status = "RUNNING"
    row.started_at = datetime.now(timezone.utc)
    row.attempts += 1
    row.next_retry_at = None
    db.commit()
    db.refresh(row)
    return row


def checkpoint(db: Session, row: AgentRun, phase: str, state_payload: dict) -> None:
    sequence = db.scalar(
        select(func.coalesce(func.max(AgentRunCheckpoint.sequence), 0) + 1).where(
            AgentRunCheckpoint.workspace_id == row.workspace_id,
            AgentRunCheckpoint.agent_run_id == row.id,
        )
    )
    db.add(AgentRunCheckpoint(
        workspace_id=row.workspace_id,
        agent_run_id=row.id,
        sequence=sequence,
        phase=phase,
        state_payload=state_payload,
    ))
    db.commit()


def refresh_form_data(workspace_id: int) -> dict:
    """Sync in a separate transaction; failed imports roll back before cached reads."""
    attempted_at = datetime.now(timezone.utc).isoformat()
    try:
        counts = sync_once(workspace_id=workspace_id)
        return {"status": "succeeded", "attempted_at": attempted_at, **counts}
    except Exception:
        # Provider and database exceptions can contain URLs, answers or SQL parameters.
        return {
            "status": "failed", "attempted_at": attempted_at,
            "error_code": "FORM_SYNC_FAILED",
            "message": "表單同步失敗，改用資料庫已保存的回覆；若無舊資料則回報資料不足。",
        }


def create_generated_content_draft(db: Session, row: AgentRun) -> dict:
    """Create a DRAFT/SCHEDULED action from a persisted strategy without HTTP model work."""
    payload = row.input_payload
    request = ContentDraftGenerateRequest.model_validate(payload)
    strategy = db.scalar(
        select(Strategy).where(Strategy.id == payload["strategy_id"], Strategy.workspace_id == row.workspace_id)
    )
    if strategy is None:
        raise RuntimeError("Strategy is unavailable for this workspace")
    goal = db.scalar(
        select(Goal).where(Goal.id == strategy.goal_id, Goal.workspace_id == row.workspace_id)
    )
    if goal is None:
        raise RuntimeError("Goal is unavailable for this workspace")
    draft = generate_content_draft(
        goal=goal,
        strategy=strategy,
        provider=row.agent_provider,
        model_name=row.agent_model,
        content_format=request.content_format,
        scheduled_at=request.scheduled_at,
        schedule_requested=request.schedule_requested,
    )
    action, created = create_content_draft(db, strategy=strategy, data=draft)
    return {
        "job_type": "CONTENT_DRAFT",
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "content_draft_action_id": action.id,
        "content_draft_created": created,
        "content_draft": action.payload,
    }


def process_one_run() -> str | None:
    """Process one queued run and return its run_id, or None when the queue is empty."""
    with SessionLocal() as db:
        row = claim_next_run(db)
        if row is None:
            return None
        payload = row.input_payload
        workspace_id, provider, model_name = row.workspace_id, row.agent_provider, row.agent_model
        checkpoint(db, row, "RUNNING", {"input": payload, "attempt": row.attempts})
        try:
            if payload.get("job_type") == "CONTENT_DRAFT":
                output = create_generated_content_draft(db, row)
                form_sync = None
            else:
                # The analysis job refreshes before reading its bounded Neon summary.
                form_sync = refresh_form_data(workspace_id)
                output = run_agent(
                    workspace_id=workspace_id,
                    goal=payload["goal"],
                    context=payload.get("context", ""),
                    constraints=payload.get("constraints", {}),
                    provider=provider,
                    model_name=model_name,
                )
                form_sync["fallback_used"] = (
                    form_sync["status"] == "failed" and output.get("form_summary", {}).get("response_count", 0) > 0
                )
                output["form_sync"] = form_sync
                if form_sync["status"] == "failed":
                    note = "表單同步失敗，本次沿用 Neon 已保存資料。" if form_sync["fallback_used"] else "表單同步失敗，資料庫沒有可用回覆，本次資料不足。"
                    output["reason"] = note + output.get("reason", "")
                # When the Strategy producer persists its formal record and
                # exposes strategy_id, automatically queue the next bounded
                # job. The new job creates the carousel draft separately.
                strategy_id = output.get("strategy_id")
                if isinstance(strategy_id, int) and not isinstance(strategy_id, bool):
                    content_run = queue_content_draft_run(
                        db,
                        workspace_id=workspace_id,
                        strategy_id=strategy_id,
                        provider=provider,
                        model_name=model_name,
                    )
                    output["content_draft_run_id"] = content_run.run_id
            row.output_payload = output
            row.status = "COMPLETED"
        except Exception:
            row.status = "FAILED"
            row.error_code = "AGENT_RUN_FAILED"
            row.error_message = "Agent run could not be completed"
        row.finished_at = datetime.now(timezone.utc)
        db.commit()
        checkpoint(db, row, row.status, {
            "error_code": row.error_code,
            "output_saved": row.output_payload is not None,
            "form_sync": form_sync,
        })
        return row.run_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued Agent runs.")
    parser.add_argument("--once", action="store_true", help="Process at most one run.")
    args = parser.parse_args()
    while True:
        with SessionLocal() as db:
            pub_result = process_scheduled_publishing(db)
            if pub_result:
                print(pub_result, flush=True)

        run_id = process_one_run()
        if run_id:
            print(f"Processed Agent run: {run_id}", flush=True)
        if args.once:
            return
        if run_id is None and pub_result is None:
            time.sleep(settings.agent_worker_poll_seconds)


if __name__ == "__main__":
    main()
