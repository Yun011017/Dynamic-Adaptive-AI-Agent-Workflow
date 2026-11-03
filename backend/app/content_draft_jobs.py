"""Queue content-draft work without running a model in the HTTP process."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from .models import AgentRun


def queue_content_draft_run(
    db: Session,
    *,
    workspace_id: int,
    strategy_id: int,
    provider: str,
    model_name: str,
    content_format: str = "carousel",
    scheduled_at: datetime | None = None,
    schedule_requested: bool = False,
) -> AgentRun:
    row = AgentRun(
        workspace_id=workspace_id,
        run_id=str(uuid.uuid4()),
        status="PENDING",
        input_payload={
            "job_type": "CONTENT_DRAFT",
            "strategy_id": strategy_id,
            "channel": "instagram",
            "content_format": content_format,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
            "schedule_requested": schedule_requested,
        },
        agent_provider=provider,
        agent_model=model_name,
    )
    db.add(row)
    db.flush()
    return row
