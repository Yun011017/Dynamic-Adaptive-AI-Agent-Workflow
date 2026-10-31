"""Read workspace-scoped form events and expose only allowlisted aggregates."""
import hashlib
import json
import math
from statistics import mean

from sqlalchemy import select

from .config import settings
from .form_sync import PROVIDER


def summarize_answers(answers, *, numeric_fields, source_id):
    numeric = {}
    for field in numeric_fields:
        values = [row.get(field) for row in answers]
        valid = [value for value in values if type(value) in (int, float) and math.isfinite(value)]
        numeric[field] = {
            'count': len(valid), 'missing_or_invalid': len(answers) - len(valid),
            'min': min(valid) if valid else None, 'max': max(valid) if valid else None,
            'mean': mean(valid) if valid else None,
        }
    summary = {
        'source': 'neon_form_summary', 'source_id': source_id,
        'response_count': len(answers), 'numeric_fields': numeric,
        'notice': '數值欄位僅做描述統計，未定義業務意義，不能推論活動偏好。',
    }
    summary['summary_id'] = hashlib.sha256(json.dumps(summary, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return summary


def get_form_summary(*, workspace_id=None):
    """No user/model-selected workspace, URL, raw rows, or arbitrary fields."""
    from .db import SessionLocal
    from .models import ExternalEvent, Workspace

    fields = list(dict.fromkeys(field.strip() for field in settings.google_forms_agent_numeric_fields.split(',') if field.strip()))
    with SessionLocal() as db:
        if workspace_id is None:
            workspace_id = db.scalar(select(Workspace.id).where(
                Workspace.slug == settings.platform_workspace_slug, Workspace.status == 'active'))
        elif db.scalar(select(Workspace.id).where(Workspace.id == workspace_id, Workspace.status == 'active')) is None:
            raise ValueError('Active workspace not found')
        if workspace_id is None:
            raise ValueError('Configured active workspace not found')
        payloads = db.scalars(select(ExternalEvent.raw_payload).where(
            ExternalEvent.workspace_id == workspace_id,
            ExternalEvent.provider == PROVIDER,
            ExternalEvent.source_account == settings.google_forms_source_id,
            ExternalEvent.event_type == 'form_response',
            ExternalEvent.source_version == 'content-sha256-v1',
        )).all()
    answers = []
    for payload in payloads:
        if not isinstance(payload, dict) or not isinstance(payload.get('answers'), dict):
            raise ValueError('Stored form response has an invalid shape')
        answers.append({field: payload['answers'].get(field) for field in fields})
    return summarize_answers(answers, numeric_fields=fields, source_id=settings.google_forms_source_id)
