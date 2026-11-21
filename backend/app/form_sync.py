"""One-shot table ingestion into external_events, independent of model execution."""
import hashlib
import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert

from .config import settings

PROVIDER = 'google_forms_apps_script'
MAX_BYTES = 2_000_000


class FormSyncError(ValueError):
    """Sanitized error suitable for the command output."""


def validate_url(url, *, redirect=False):
    try:
        parsed = urlsplit(url)
        hosts = {'script.google.com', 'script.googleusercontent.com'} if redirect else {'script.google.com'}
        valid = (parsed.scheme == 'https' and parsed.hostname in hosts
                 and not parsed.username and not parsed.password and parsed.port in (None, 443))
        if not redirect:
            valid = valid and parsed.path.startswith('/macros/s/') and parsed.path.endswith('/exec') and not parsed.fragment
    except ValueError:
        valid = False
    if not valid:
        raise FormSyncError('Invalid Apps Script Google HTTPS deployment URL')


class GoogleRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_table(url=None):
    url = (settings.google_forms_apps_script_url if url is None else url).strip()
    validate_url(url)
    try:
        with build_opener(GoogleRedirects()).open(url, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1)
    except (URLError, TimeoutError, OSError):
        raise FormSyncError('Cannot read Apps Script; check network and deployment access') from None
    if len(raw) > MAX_BYTES:
        raise FormSyncError('Apps Script response exceeds 2 MB')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise FormSyncError('Apps Script response is not valid JSON') from None


def parse_responses(table):
    """Preserve cells and header names exactly; canonical JSON supplies identity."""
    if isinstance(table, dict):
        if table.get('success') is not True or not isinstance(table.get('data'), dict):
            raise FormSyncError('Invalid Apps Script result envelope')
        groups = table['data']
        if not groups or set(groups) - {'人工', 'ai'}:
            raise FormSyncError('Expected human/ai response groups')
        records = []
        source_column = settings.google_forms_source_column
        for source, rows in groups.items():
            if not isinstance(rows, list):
                raise FormSyncError('Expected response records in each group')
            for row in rows:
                if not isinstance(row, dict) or not row:
                    raise FormSyncError('Expected nonempty response records')
                if any(not isinstance(key, str) or not key.strip() for key in row):
                    raise FormSyncError('Invalid response field names')
                if source_column in row and row[source_column] != source:
                    raise FormSyncError('Conflicting response source')
                records.append({**row, source_column: source})
        headers = sorted({key for row in records for key in row}) or [source_column]
        table = [headers] + [[row.get(key) for key in headers] for row in records]
    if not isinstance(table, list) or not table or not isinstance(table[0], list):
        raise FormSyncError('Expected a table with a header row')
    headers = table[0]
    if (not headers or not all(isinstance(key, str) and key.strip() for key in headers)
            or len(set(headers)) != len(headers)):
        raise FormSyncError('Headers must be unique nonempty strings')
    results = []
    for row in table[1:]:
        if not isinstance(row, list) or len(row) != len(headers):
            raise FormSyncError('Response width does not match headers')
        if any(type(value) not in (str, int, float, bool, type(None))
               or isinstance(value, float) and not math.isfinite(value) for value in row):
            raise FormSyncError('Response cells must be finite JSON scalar values')
        if all(value is None or value == '' for value in row):
            continue
        answers = dict(zip(headers, row))
        canonical = json.dumps(answers, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        results.append((digest, answers))
    return results


def save_responses(db, responses, *, workspace_slug, source_id, naive_timezone=None, use_legacy_mapping=True):
    """Caller commits the whole batch. ON CONFLICT also protects concurrent imports."""
    if not source_id.strip() or len(source_id) > 255:
        raise FormSyncError('Form source ID must be nonempty and at most 255 characters')
    from .models import ExternalEvent, Workspace, FormResponse, Execution, FormExecutionBinding
    from .form_fields import normalize_fields

    workspace_id = db.scalar(select(Workspace.id).where(Workspace.slug == workspace_slug, Workspace.status == 'active').with_for_update())
    if workspace_id is None:
        raise FormSyncError('Configured active workspace does not exist')
    bindings = {row.copy_source: row.execution_id for row in db.scalars(
        select(FormExecutionBinding).where(FormExecutionBinding.workspace_id == workspace_id,
                                          FormExecutionBinding.source_id == source_id)).all()}
    # Validate all attribution before writing any events. IDs belong to this tenant.
    prepared = []
    checked_executions = set()
    for digest, answers in responses:
        fields = normalize_fields(answers, naive_timezone=naive_timezone)
        if 'copy_source:unknown_value' in fields['normalization_errors']:
            raise FormSyncError('Unknown registration copy source')
        fallback = settings.google_forms_execution_map.get(fields['copy_source']) if use_legacy_mapping else None
        execution_id = bindings.get(fields['copy_source'], fallback)
        if execution_id is not None and execution_id not in checked_executions:
            if type(execution_id) is not int or execution_id <= 0:
                raise FormSyncError('Invalid configured registration execution')
            execution = db.scalar(select(Execution.id).where(
                Execution.workspace_id == workspace_id, Execution.id == execution_id))
            if execution is None:
                raise FormSyncError('Registration execution does not belong to this workspace')
            checked_executions.add(execution_id)
        fields['execution_id'] = execution_id
        prepared.append((digest, answers, fields))
    inserted = 0
    fetched_at = datetime.now(timezone.utc).isoformat()
    for digest, answers, fields in prepared:
        statement = insert(ExternalEvent).values(
            workspace_id=workspace_id, provider=PROVIDER, source_account=source_id,
            source_object_id=digest, source_version='content-sha256-v1',
            event_type='form_response', processing_status='RECEIVED',
            raw_payload={'answers': answers, 'fetched_at': fetched_at},
        ).on_conflict_do_nothing(constraint='uq_external_event_source').returning(ExternalEvent.id)
        event_id = db.scalar(statement)
        inserted += event_id is not None
        if event_id is None:
            event_id = db.scalar(select(ExternalEvent.id).where(
                ExternalEvent.workspace_id == workspace_id, ExternalEvent.provider == PROVIDER,
                ExternalEvent.source_account == source_id, ExternalEvent.source_object_id == digest,
                ExternalEvent.source_version == 'content-sha256-v1'))
        if event_id is None:
            raise FormSyncError('Cannot resolve stored form response')
        statement = insert(FormResponse).values(
            workspace_id=workspace_id, external_event_id=event_id, source_id=source_id, **fields,
        )
        updates = {**fields, 'execution_id': func.coalesce(FormResponse.execution_id, statement.excluded.execution_id)}
        saved_id = db.scalar(statement.on_conflict_do_update(
            constraint='uq_form_response_event', set_=updates,
            where=or_(FormResponse.execution_id.is_(None), statement.excluded.execution_id.is_(None),
                      FormResponse.execution_id == statement.excluded.execution_id),
        ).returning(FormResponse.id))
        if saved_id is None:
            raise FormSyncError('Existing registration execution cannot be reassigned')
    return {'read': len(responses), 'inserted': inserted, 'skipped': len(responses) - inserted}


def sync_once(*, workspace_id=None, goal_id=None):
    from .db import SessionLocal
    from .models import Workspace, FormSource
    from .form_sources import sync_registered_source
    with SessionLocal() as db:
        scope = Workspace.id == workspace_id if workspace_id is not None else Workspace.slug == settings.platform_workspace_slug
        registered = list(db.scalars(select(FormSource).join(Workspace, Workspace.id == FormSource.workspace_id)
                                     .where(scope, Workspace.status == 'active')).all())
        targets = [(row.id, row.workspace_id) for row in registered
                   if row.enabled and (goal_id is None or row.goal_id == goal_id)]
    if registered:
        total = dict(read=0, inserted=0, skipped=0)
        for pk, tenant in targets:
            counts = sync_registered_source(pk, tenant)
            for key in total:
                total[key] += counts[key]
        return total
    # Fetch and validate before opening a database transaction.
    responses = parse_responses(fetch_table())
    with SessionLocal.begin() as db:
        if workspace_id is not None:
            # The configured external source belongs only to this deployment's workspace.
            authorized = db.scalar(select(Workspace.id).where(
                Workspace.id == workspace_id, Workspace.slug == settings.platform_workspace_slug,
                Workspace.status == 'active'))
            if authorized is None:
                raise FormSyncError('Form source is not configured for this workspace')
        return save_responses(db, responses, workspace_slug=settings.platform_workspace_slug,
                              source_id=settings.google_forms_source_id)
