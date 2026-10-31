"""One-shot table ingestion into external_events, independent of model execution."""
import hashlib
import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from sqlalchemy import select
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
            valid = valid and parsed.path.startswith('/macros/s/') and parsed.path.endswith('/exec')
    except ValueError:
        valid = False
    if not valid:
        raise FormSyncError('Invalid Apps Script Google HTTPS deployment URL')


class GoogleRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_table():
    url = settings.google_forms_apps_script_url.strip()
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


def save_responses(db, responses, *, workspace_slug, source_id):
    """Caller commits the whole batch. ON CONFLICT also protects concurrent imports."""
    if not source_id.strip() or len(source_id) > 255:
        raise FormSyncError('Form source ID must be nonempty and at most 255 characters')
    from .models import ExternalEvent, Workspace, FormResponse
    from .form_fields import normalize_fields

    workspace_id = db.scalar(select(Workspace.id).where(Workspace.slug == workspace_slug, Workspace.status == 'active'))
    if workspace_id is None:
        raise FormSyncError('Configured active workspace does not exist')
    inserted = 0
    fetched_at = datetime.now(timezone.utc).isoformat()
    for digest, answers in responses:
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
        fields = normalize_fields(answers)
        db.execute(insert(FormResponse).values(
            workspace_id=workspace_id, external_event_id=event_id, source_id=source_id, **fields,
        ).on_conflict_do_update(constraint='uq_form_response_event', set_=fields))
    return {'read': len(responses), 'inserted': inserted, 'skipped': len(responses) - inserted}


def sync_once():
    from .db import SessionLocal
    # Fetch and validate before opening a database transaction.
    responses = parse_responses(fetch_table())
    with SessionLocal.begin() as db:
        return save_responses(db, responses, workspace_slug=settings.platform_workspace_slug,
                              source_id=settings.google_forms_source_id)
