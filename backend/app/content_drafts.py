"""Content-draft persistence shared by API endpoints and future Agent nodes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Execution, ExecutionAction, Strategy
from .schemas import ContentDraftCreate


def render_caption(caption: str, hashtags: list[str]) -> str:
    """Return the exact text the Meta adapter will receive; never include secrets."""
    tag_line = " ".join(f"#{tag}" for tag in hashtags)
    return f"{caption.strip()}\n\n{tag_line}".rstrip()


def _payload(strategy: Strategy, data: ContentDraftCreate) -> dict:
    scheduled_at = data.scheduled_at.isoformat() if data.scheduled_at else None
    image_urls = list(data.image_urls)
    return {
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "channel": data.channel,
        "caption": data.caption.strip(),
        "hashtags": list(data.hashtags),
        "image_requirements": list(data.image_requirements),
        "image_urls": image_urls,
        "carousel": data.carousel,
        "scheduled_at": scheduled_at,
        # The current Meta sandbox can publish only one public image. A carousel
        # remains a platform draft until that adapter adds carousel support.
        "meta_adapter_payload": (
            {"image_url": image_urls[0], "caption": render_caption(data.caption, data.hashtags)}
            if len(image_urls) == 1 and not data.carousel
            else None
        ),
    }


def _hash(value: dict) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_content_draft(
    db: Session,
    *,
    strategy: Strategy,
    data: ContentDraftCreate,
) -> tuple[ExecutionAction, bool]:
    """Create one content action, or return the same action for an identical request."""
    payload = _payload(strategy, data)
    content_hash = _hash({key: value for key, value in payload.items() if key != "scheduled_at"})
    idempotency_key = _hash(payload)
    existing = db.scalar(
        select(ExecutionAction).where(
            ExecutionAction.workspace_id == strategy.workspace_id,
            ExecutionAction.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing, False

    execution = Execution(
        workspace_id=strategy.workspace_id,
        strategy_id=strategy.id,
        status="WAITING_APPROVAL",
    )
    db.add(execution)
    db.flush()
    action = ExecutionAction(
        workspace_id=strategy.workspace_id,
        execution_id=execution.id,
        tool="meta_api",
        operation="instagram_publish",
        status="SCHEDULED" if data.scheduled_at else "DRAFT",
        draft_version=1,
        content_hash=content_hash,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    db.add(action)
    db.flush()
    return action, True


def create_content_draft_version(
    db: Session,
    *,
    previous: ExecutionAction,
    strategy: Strategy,
    data: ContentDraftCreate,
) -> ExecutionAction:
    """Keep the previous immutable draft and replace it with the next version."""
    payload = _payload(strategy, data)
    content_hash = _hash({key: value for key, value in payload.items() if key != "scheduled_at"})
    version = previous.draft_version + 1
    # Include the version because an intentional edit may restore earlier text.
    idempotency_key = _hash({"execution_id": previous.execution_id, "version": version, **payload})
    previous.status = "SUPERSEDED"
    action = ExecutionAction(
        workspace_id=previous.workspace_id,
        execution_id=previous.execution_id,
        tool="meta_api",
        operation="instagram_publish",
        status="SCHEDULED" if data.scheduled_at else "DRAFT",
        draft_version=version,
        content_hash=content_hash,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    db.add(action)
    db.flush()
    return action
