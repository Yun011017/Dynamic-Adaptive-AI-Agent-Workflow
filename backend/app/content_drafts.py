"""Content-draft persistence shared by API endpoints and future Agent nodes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .models import Execution, ExecutionAction, Strategy
from .schemas import ContentDraftCreate


def render_caption(caption: str, hashtags: list[str]) -> str:
    """Return the exact text the Meta adapter will receive; never include secrets."""
    tag_line = " ".join(f"#{tag}" for tag in hashtags)
    return f"{caption.strip()}\n\n{tag_line}".rstrip()


def meta_adapter_payload(
    *, caption: str, hashtags: list[str], image_urls: list[str], carousel: bool
) -> dict | None:
    """Build provider-safe input without performing a Meta publish request."""
    rendered_caption = render_caption(caption, hashtags)
    if carousel and len(image_urls) >= 2:
        return {
            "media_type": "CAROUSEL",
            "caption": rendered_caption,
            "children": [
                {"image_url": url, "is_carousel_item": True}
                for url in image_urls
            ],
        }
    if not carousel and len(image_urls) == 1:
        return {
            "media_type": "IMAGE",
            "image_url": image_urls[0],
            "caption": rendered_caption,
        }
    return None


def _payload(
    strategy: Strategy, data: ContentDraftCreate, *, proposal_version: int | None = None
) -> dict:
    scheduled_at = data.scheduled_at.isoformat() if data.scheduled_at else None
    image_urls = list(data.image_urls)
    payload = {
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "channel": data.channel,
        "title": data.title.strip(),
        "caption": data.caption.strip(),
        "hashtags": list(data.hashtags),
        "image_requirements": list(data.image_requirements),
        "image_urls": image_urls,
        "carousel": data.carousel,
        "scheduled_at": scheduled_at,
        "schedule_requested": data.schedule_requested,
        # This is provider input only; the approval/publishing worker owns the
        # later container creation and publish request.
        "meta_adapter_payload": meta_adapter_payload(
            caption=data.caption,
            hashtags=list(data.hashtags),
            image_urls=image_urls,
            carousel=data.carousel,
        ),
    }
    if proposal_version is not None:
        payload["proposal_version"] = proposal_version
    return payload


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
    identity_payload = _payload(strategy, data)
    idempotency_key = _hash(identity_payload)
    existing = db.scalar(
        select(ExecutionAction).where(
            ExecutionAction.workspace_id == strategy.workspace_id,
            ExecutionAction.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing, False

    proposal_version = (
        db.scalar(
            select(func.count())
            .select_from(ExecutionAction)
            .join(Execution, Execution.id == ExecutionAction.execution_id)
            .where(
                ExecutionAction.workspace_id == strategy.workspace_id,
                Execution.workspace_id == strategy.workspace_id,
                Execution.strategy_id == strategy.id,
                ExecutionAction.draft_version == 1,
            )
        )
        + 1
    )
    payload = _payload(strategy, data, proposal_version=proposal_version)
    content_hash = _hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"scheduled_at", "proposal_version"}
        }
    )

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
        status="SCHEDULED" if data.schedule_requested else "DRAFT",
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
    proposal_version = previous.payload.get("proposal_version", 1)
    payload = _payload(strategy, data, proposal_version=proposal_version)
    content_hash = _hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"scheduled_at", "proposal_version"}
        }
    )
    # A user may restore any historical version. New content must always become
    # the next version in the proposal, rather than colliding with an existing
    # successor of the selected historical row.
    version = (
        db.scalar(
            select(func.coalesce(func.max(ExecutionAction.draft_version), 0)).where(
                ExecutionAction.workspace_id == previous.workspace_id,
                ExecutionAction.execution_id == previous.execution_id,
            )
        )
        + 1
    )
    # Include the version because an intentional edit may restore earlier text.
    idempotency_key = _hash({"execution_id": previous.execution_id, "version": version, **payload})
    db.execute(
        update(ExecutionAction)
        .where(
            ExecutionAction.workspace_id == previous.workspace_id,
            ExecutionAction.execution_id == previous.execution_id,
            ExecutionAction.status.not_in({"SUPERSEDED", "EXECUTING", "SUCCEEDED"}),
        )
        .values(status="SUPERSEDED")
    )
    action = ExecutionAction(
        workspace_id=previous.workspace_id,
        execution_id=previous.execution_id,
        tool="meta_api",
        operation="instagram_publish",
        status="SCHEDULED" if data.schedule_requested else "DRAFT",
        draft_version=version,
        content_hash=content_hash,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    db.add(action)
    db.flush()
    return action
