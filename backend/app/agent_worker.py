"""Database-backed worker for bounded Agent runs.

Run with ``python -m app.agent_worker`` from ``backend/``. The worker claims
only PENDING records, so multiple workers can poll the same Neon database.
"""
import argparse
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_runner import run_agent
from .config import settings
from .db import SessionLocal
from .models import AgentRun


def claim_next_run(db: Session) -> AgentRun | None:
    """Atomically move one waiting run to RUNNING, skipping another worker's lock."""
    row = db.scalars(
        select(AgentRun)
        .where(AgentRun.status == "PENDING")
        .order_by(AgentRun.created_at, AgentRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if row is None:
        return None
    row.status = "RUNNING"
    row.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def process_one_run() -> str | None:
    """Process one queued run and return its run_id, or None when the queue is empty."""
    with SessionLocal() as db:
        row = claim_next_run(db)
        if row is None:
            return None
        payload = row.input_payload
        try:
            row.output_payload = run_agent(
                goal=payload["goal"],
                context=payload.get("context", ""),
                constraints=payload.get("constraints", {}),
            )
            row.status = "COMPLETED"
        except Exception:
            row.status = "FAILED"
            row.error_code = "AGENT_RUN_FAILED"
            row.error_message = "Agent run could not be completed"
        row.finished_at = datetime.now(timezone.utc)
        db.commit()
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
