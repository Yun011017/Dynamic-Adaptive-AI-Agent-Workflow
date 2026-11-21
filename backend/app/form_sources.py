"""Activity-owned form registrations; URLs remain server-side."""
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from .config import settings
from .models import Execution, FormExecutionBinding, FormResponse, FormSource, Goal, Strategy, Workspace


def source_read(row):
    return dict(id=row.id, source_id=row.source_id, name=row.name, goal_id=row.goal_id,
                timezone=row.timezone, enabled=row.enabled)


def activity_source_ids(db, workspace_id, goal_id=None):
    rows = list(db.scalars(select(FormSource).where(FormSource.workspace_id == workspace_id)).all())
    if rows:
        return [row.source_id for row in rows if goal_id is None or row.goal_id == goal_id]
    return [settings.google_forms_source_id]


def create_source(db, workspace_id, data):
    db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
    if db.scalar(select(Goal.id).where(Goal.id == data.goal_id, Goal.workspace_id == workspace_id)) is None:
        raise HTTPException(404, '找不到活動')
    if db.scalar(select(FormSource.id).where(FormSource.workspace_id == workspace_id,
                                            FormSource.apps_script_url == data.apps_script_url)) is not None:
        raise HTTPException(409, '這個 Apps Script 網址已新增，請使用既有來源')
    # Adopt the existing env endpoint without duplicating its historical responses.
    source_id = 'form-' + uuid.uuid4().hex
    slug = db.scalar(select(Workspace.slug).where(Workspace.id == workspace_id))
    if slug == settings.platform_workspace_slug and data.apps_script_url == settings.google_forms_apps_script_url.strip():
        source_id = settings.google_forms_source_id
        foreign_binding = db.scalar(select(FormExecutionBinding.id).join(
            Execution, (Execution.id == FormExecutionBinding.execution_id)
            & (Execution.workspace_id == FormExecutionBinding.workspace_id)).join(
            Strategy, (Strategy.id == Execution.strategy_id) & (Strategy.workspace_id == Execution.workspace_id)
        ).where(FormExecutionBinding.workspace_id == workspace_id, FormExecutionBinding.source_id == source_id,
                Strategy.goal_id != data.goal_id).limit(1))
        if foreign_binding is not None:
            raise HTTPException(409, '既有來源已綁定其他活動的執行，無法移至此活動')
        foreign_response = db.scalar(select(FormResponse.id).join(
            Execution, (Execution.id == FormResponse.execution_id) & (Execution.workspace_id == FormResponse.workspace_id)
        ).join(Strategy, (Strategy.id == Execution.strategy_id) & (Strategy.workspace_id == Execution.workspace_id))
          .where(FormResponse.workspace_id == workspace_id, FormResponse.source_id == source_id,
                 Strategy.goal_id != data.goal_id).limit(1))
        if foreign_response is not None:
            raise HTTPException(409, '既有報名已關聯其他活動，無法移至此活動')
    row = FormSource(workspace_id=workspace_id, source_id=source_id, **data.model_dump(), enabled=True)
    db.add(row)
    db.flush()
    return row


def sync_registered_source(source_pk, workspace_id):
    from .db import SessionLocal
    from .form_sync import FormSyncError, fetch_table, parse_responses, save_responses
    with SessionLocal() as db:
        row = db.scalar(select(FormSource).where(FormSource.id == source_pk, FormSource.workspace_id == workspace_id))
        if row is None:
            raise HTTPException(404, '找不到表單來源')
        if not row.enabled:
            raise HTTPException(409, '此表單來源已停用，請先啟用')
        source_id, url, timezone = row.source_id, row.apps_script_url, row.timezone
        slug = db.scalar(select(Workspace.slug).where(Workspace.id == workspace_id, Workspace.status == 'active'))
        if slug is None:
            raise HTTPException(404, '找不到啟用中的工作區')
    # No database transaction is held while waiting on Google.
    responses = parse_responses(fetch_table(url))
    with SessionLocal.begin() as db:
        db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
        row = db.scalar(select(FormSource).where(FormSource.id == source_pk, FormSource.workspace_id == workspace_id))
        if row is None or not row.enabled:
            raise FormSyncError('Form source was disabled during synchronization')
        return save_responses(db, responses, workspace_slug=slug, source_id=source_id,
                              naive_timezone=timezone, use_legacy_mapping=False)
