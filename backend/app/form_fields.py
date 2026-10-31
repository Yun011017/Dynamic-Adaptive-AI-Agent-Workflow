"""Explicit question mappings; absent/unknown answers never become False."""
import unicodedata
from datetime import date, datetime, timezone, timedelta

from .config import settings


def normalize_fields(answers):
    errors = []

    def boolean(column, field, yes, no):
        value = answers.get(column)
        if value is None or value == '':
            return None
        if type(value) is bool:
            return value
        if isinstance(value, str):
            cleaned = unicodedata.normalize('NFKC', value).strip().lower()
            if not cleaned:
                return None
            if cleaned in yes:
                return True
            if cleaned in no:
                return False
        errors.append(field + ':unknown_value')
        return None

    is_member = boolean(settings.google_forms_member_column, 'is_member',
                        {'是', '是社員', '社員', 'yes', 'true'}, {'否', '不是社員', '非社員', 'no', 'false'})
    will_attend = boolean(settings.google_forms_attendance_column, 'will_attend',
                          {'是', '要', '參加', '會參加', 'yes', 'true'}, {'否', '不要', '不參加', '不會參加', 'no', 'false'})
    event_date = submitted_at = None
    value = answers.get(settings.google_forms_event_date_column)
    if value is not None and value != '':
        try:
            if not isinstance(value, str):
                raise ValueError()
            text = value.strip().replace('/', '-')
            if 'T' in text:
                parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError()
                event_date = parsed.astimezone(timezone(timedelta(hours=settings.google_forms_date_utc_offset_hours))).date()
            else:
                event_date = date.fromisoformat(text)
        except ValueError:
            errors.append('event_date:invalid_date')
    value = answers.get(settings.google_forms_submitted_at_column)
    if value is not None and value != '':
        try:
            if not isinstance(value, str):
                raise ValueError()
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
            submitted_at = parsed.astimezone(timezone.utc)
        except ValueError:
            errors.append('submitted_at:invalid_or_missing_timezone')
    return dict(is_member=is_member, will_attend=will_attend, event_date=event_date,
                submitted_at=submitted_at, normalization_errors=errors)
