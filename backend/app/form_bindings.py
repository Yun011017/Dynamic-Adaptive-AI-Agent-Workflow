"""Tenant-scoped registration attribution without exposing personal answers."""
from fastapi import HTTPException
from sqlalchemy import select, func, update

from .config import settings
from .models import Execution, FormExecutionBinding, FormResponse, FormSource, Strategy, Workspace


def list_form_sources(db, workspace_id):
    sources = {}
    for source, copy, count in db.execute(select(
        FormResponse.source_id, FormResponse.copy_source, func.count(FormResponse.id)
    ).where(FormResponse.workspace_id == workspace_id,
            FormResponse.copy_source.in_(['人工', 'ai']))
      .group_by(FormResponse.source_id, FormResponse.copy_source)):
        sources[(source, copy)] = dict(source_id=source, copy_source=copy, response_count=count, execution_id=None)
    for row in db.scalars(select(FormExecutionBinding).where(FormExecutionBinding.workspace_id == workspace_id)):
        item = sources.setdefault((row.source_id, row.copy_source), dict(
            source_id=row.source_id, copy_source=row.copy_source, response_count=0, execution_id=None))
        item['execution_id'] = row.execution_id
    slug = db.scalar(select(Workspace.slug).where(Workspace.id == workspace_id))
    if slug == settings.platform_workspace_slug and settings.google_forms_apps_script_url:
        for copy in ('人工', 'ai'):
            sources.setdefault((settings.google_forms_source_id, copy), dict(
                source_id=settings.google_forms_source_id, copy_source=copy, response_count=0, execution_id=None))
    for registered in db.scalars(select(FormSource).where(FormSource.workspace_id == workspace_id)):
        for copy in ('人工', 'ai'):
            item = sources.setdefault((registered.source_id, copy), dict(
                source_id=registered.source_id, copy_source=copy, response_count=0, execution_id=None))
            item.update(name=registered.name, goal_id=registered.goal_id, enabled=registered.enabled)
    return [sources[key] for key in sorted(sources)]


def bind_form_source(db, workspace_id, execution_id, source_id, copy_source):
    # Import and UI binding serialize on the same workspace row, including first binding.
    db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
    if db.scalar(select(Execution.id).where(Execution.workspace_id == workspace_id,
                                          Execution.id == execution_id)) is None:
        raise HTTPException(404, '找不到這個執行紀錄')
    registered = db.scalar(select(FormSource).where(FormSource.workspace_id == workspace_id,
                                                   FormSource.source_id == source_id))
    if registered is not None:
        execution_goal = db.scalar(select(Strategy.goal_id).join(
            Execution, (Execution.strategy_id == Strategy.id) & (Execution.workspace_id == Strategy.workspace_id)
        ).where(Execution.workspace_id == workspace_id, Execution.id == execution_id))
        if not registered.enabled:
            raise HTTPException(409, '此表單來源已停用')
        if execution_goal != registered.goal_id:
            raise HTTPException(409, '表單與執行紀錄必須屬於同一活動')
    if not any(row['source_id'] == source_id and row['copy_source'] == copy_source
               for row in list_form_sources(db, workspace_id)):
        raise HTTPException(404, '找不到表單來源，請先同步表單')
    binding = db.scalar(select(FormExecutionBinding).where(
        FormExecutionBinding.workspace_id == workspace_id, FormExecutionBinding.source_id == source_id,
        FormExecutionBinding.copy_source == copy_source))
    if binding is not None and binding.execution_id != execution_id:
        raise HTTPException(409, '這個表單來源已綁定其他執行，請使用獨立表單來源')
    scope = (FormResponse.workspace_id == workspace_id, FormResponse.source_id == source_id,
             FormResponse.copy_source == copy_source)
    if db.scalar(select(FormResponse.id).where(*scope, FormResponse.execution_id.is_not(None),
                                               FormResponse.execution_id != execution_id).limit(1)) is not None:
        raise HTTPException(409, '既有報名已關聯其他執行，無法重新歸因')
    if binding is None:
        db.add(FormExecutionBinding(workspace_id=workspace_id, source_id=source_id,
                                    copy_source=copy_source, execution_id=execution_id))
        db.flush()
    updated = db.execute(update(FormResponse).where(*scope, FormResponse.execution_id.is_(None))
                         .values(execution_id=execution_id)).rowcount
    return dict(source_id=source_id, copy_source=copy_source, execution_id=execution_id, backfilled=updated)
