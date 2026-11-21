"""Explicit question mappings; absent/unknown answers never become False."""
import unicodedata
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings


def normalize_fields(answers, *, naive_timezone=None):
    errors = []

    def boolean(column, field, yes, no, *, default=None):
        value = answers.get(column)
        if value is None or value == '':
            return default
        if type(value) is bool:
            return value
        if isinstance(value, str):
            cleaned = unicodedata.normalize('NFKC', value).strip().lower()
            if not cleaned:
                return default
            if cleaned in yes:
                return True
            if cleaned in no:
                return False
        errors.append(field + ':unknown_value')
        return None

    is_member = boolean(settings.google_forms_member_column, 'is_member',
                        {'是', '是社員', '社員', 'yes', 'true'}, {'否', '不是社員', '非社員', 'no', 'false'})
    will_attend = boolean(settings.google_forms_attendance_column, 'will_attend',
                          {'是', '要', '參加', '會參加', 'yes', 'true'}, {'否', '不要', '不參加', '不會參加', 'no', 'false'}, default=True)
    def text(column, field):
        value = answers.get(column)
        if value is None or value == '':
            return None
        if not isinstance(value, str):
            errors.append(field + ':invalid_text')
            return None
        normalized = ' '.join(unicodedata.normalize('NFKC', value).split())
        if len(normalized) > 255:
            errors.append(field + ':too_long')
            return None
        return normalized or None

    school = text(settings.google_forms_school_column, 'school')
    department_grade = text(settings.google_forms_department_grade_column, 'department_grade')
    activity_name = text(settings.google_forms_activity_column, 'activity_name')
    email = text(settings.google_forms_email_column, 'email')
    respondent_name = text(settings.google_forms_name_column, 'respondent_name')
    copy_source = text(settings.google_forms_source_column, 'copy_source')
    if copy_source:
        copy_source = copy_source.lower()
        if copy_source not in {'人工', 'ai'}:
            errors.append('copy_source:unknown_value')
            copy_source = None
    submitted_at = None
    value = answers.get(settings.google_forms_submitted_at_column)
    if value is not None and value != '':
        try:
            if not isinstance(value, str):
                raise ValueError()
            cleaned = value.strip()
            try:
                parsed = datetime.fromisoformat(cleaned.replace('Z', '+00:00'))
            except ValueError:
                local = re.fullmatch(r'(\d{4}/\d{1,2}/\d{1,2})\s+(上午|下午)\s*(\d{1,2}):(\d{2}):(\d{2})', cleaned)
                if local:
                    day, period, hour, minute, second = local.groups()
                    hour = int(hour)
                    if not 1 <= hour <= 12:
                        raise ValueError()
                    hour = hour % 12 + (12 if period == '下午' else 0)
                    cleaned = f'{day} {hour:02d}:{minute}:{second}'
                parsed = datetime.strptime(cleaned, '%Y/%m/%d %H:%M:%S')
            if parsed.tzinfo is None:
                source_timezone = settings.google_forms_naive_timezone if naive_timezone is None else naive_timezone
                if not source_timezone:
                    raise ValueError()
                parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone))
            submitted_at = parsed.astimezone(timezone.utc)
        except (ValueError, ZoneInfoNotFoundError):
            errors.append('submitted_at:invalid_or_missing_timezone')
    return dict(is_member=is_member, will_attend=will_attend, school=school,
                department_grade=department_grade, activity_name=activity_name,
                submitted_at=submitted_at, email=email, respondent_name=respondent_name,
                copy_source=copy_source, normalization_errors=errors)
