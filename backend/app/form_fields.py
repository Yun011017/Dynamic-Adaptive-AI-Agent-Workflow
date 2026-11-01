"""Explicit question mappings; absent/unknown answers never become False."""
import unicodedata
from datetime import datetime, timezone

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
    submitted_at = None
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
    return dict(is_member=is_member, will_attend=will_attend, school=school,
                department_grade=department_grade, activity_name=activity_name,
                submitted_at=submitted_at, normalization_errors=errors)
