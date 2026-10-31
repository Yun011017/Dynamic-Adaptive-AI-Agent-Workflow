"""Workspace-scoped aggregates of structured form_responses, never raw answers."""
import hashlib
import json
from collections import Counter
from datetime import timezone

from sqlalchemy import select

from .config import settings
from .form_sync import PROVIDER


def summarize_responses(responses, *, source_id):
    def boolean_counts(field):
        return {
            "yes": sum(row.get(field) is True for row in responses),
            "no": sum(row.get(field) is False for row in responses),
            "unknown": sum(row.get(field) is None for row in responses),
        }

    dates = Counter(row["event_date"].isoformat() for row in responses if row.get("event_date") is not None)
    submitted = [row["submitted_at"].astimezone(timezone.utc) for row in responses if row.get("submitted_at") is not None]
    summary = {
        "source": "neon_form_summary", "storage_table": "form_responses", "source_id": source_id,
        "response_count": len(responses),
        "membership": boolean_counts("is_member"),
        "attendance": boolean_counts("will_attend"),
        "event_dates": dict(sorted(dates.items())),
        "event_date_unknown_count": sum(row.get("event_date") is None for row in responses),
        "submission_period": {
            "known_count": len(submitted), "unknown_count": len(responses) - len(submitted),
            "first": min(submitted).isoformat() if submitted else None,
            "last": max(submitted).isoformat() if submitted else None,
        },
        "normalization_error_count": sum(bool(row.get("normalization_errors")) for row in responses),
        "notice": "統計僅代表已同步回覆，不等於實際到場人數；未知值不能視為否，參加意願不代表內容偏好。",
    }
    summary["summary_id"] = hashlib.sha256(json.dumps(summary, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return summary


def get_form_summary(*, workspace_id=None):
    """Only aggregate typed fields from the configured source and authorized workspace."""
    from .db import SessionLocal
    from .models import ExternalEvent, FormResponse, Workspace

    with SessionLocal() as db:
        if workspace_id is None:
            workspace_id = db.scalar(select(Workspace.id).where(
                Workspace.slug == settings.platform_workspace_slug, Workspace.status == "active"))
        elif db.scalar(select(Workspace.id).where(Workspace.id == workspace_id, Workspace.status == "active")) is None:
            raise ValueError("Active workspace not found")
        if workspace_id is None:
            raise ValueError("Configured active workspace not found")
        responses = db.execute(select(
            FormResponse.is_member, FormResponse.will_attend, FormResponse.event_date,
            FormResponse.submitted_at, FormResponse.normalization_errors,
        ).join(ExternalEvent, (ExternalEvent.id == FormResponse.external_event_id)
               & (ExternalEvent.workspace_id == FormResponse.workspace_id)).where(
            FormResponse.workspace_id == workspace_id,
            FormResponse.source_id == settings.google_forms_source_id,
            ExternalEvent.provider == PROVIDER,
            ExternalEvent.source_account == settings.google_forms_source_id,
            ExternalEvent.event_type == "form_response",
            ExternalEvent.source_version == "content-sha256-v1",
        )).mappings().all()
    return summarize_responses(responses, source_id=settings.google_forms_source_id)
