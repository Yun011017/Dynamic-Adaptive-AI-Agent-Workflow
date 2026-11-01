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
from .form_sync import sync_once
from .config import settings
from .db import SessionLocal
from .models import AgentRun, AgentRunCheckpoint


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


def process_one_run() -> str | None:
    """Process one queued run and return its run_id, or None when the queue is empty."""
    with SessionLocal() as db:
        row = claim_next_run(db)
        if row is None:
            return None
        payload = row.input_payload
        workspace_id, provider, model_name = row.workspace_id, row.agent_provider, row.agent_model
        checkpoint(db, row, "RUNNING", {"input": payload, "attempt": row.attempts})
        # checkpoint committed the claim; no main DB transaction is held during fetching.
        form_sync = refresh_form_data(workspace_id)
        try:
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
        run_id = process_one_run()
        if run_id:
            print(f"Processed Agent run: {run_id}", flush=True)
        if args.once:
            return
        if run_id is None:
            time.sleep(settings.agent_worker_poll_seconds)


if __name__ == "__main__":
    main()
