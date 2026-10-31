import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from app.form_fields import normalize_fields
from app.config import settings


class FormFieldsTests(unittest.TestCase):
    def setUp(self):
        mappings = dict(google_forms_member_column='是否為社員', google_forms_attendance_column='是否要參加',
                        google_forms_event_date_column='活動日期', google_forms_submitted_at_column='時間戳記',
                        google_forms_date_utc_offset_hours=8)
        for name, value in mappings.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_explicit_booleans_and_dates(self):
        result = normalize_fields({'是否為社員': ' 是 ', '是否要參加': '不參加', '活動日期': '2026/11/15', '時間戳記': '2026-10-31T12:00:00+08:00'})
        self.assertIs(result['is_member'], True)
        self.assertIs(result['will_attend'], False)
        self.assertEqual(result['event_date'], date(2026, 11, 15))
        self.assertEqual(result['submitted_at'], datetime(2026, 10, 31, 4, tzinfo=timezone.utc))
        self.assertEqual(result['normalization_errors'], [])

    def test_test_columns_do_not_become_business_fields(self):
        result = normalize_fields({'test': 1, 'temp': 6})
        self.assertIsNone(result['is_member'])
        self.assertIsNone(result['will_attend'])
        self.assertIsNone(result['event_date'])
        self.assertIsNone(result['submitted_at'])
        self.assertEqual(result['normalization_errors'], [])

    def test_unknown_and_invalid_are_not_false(self):
        result = normalize_fields({'是否為社員': 1, '是否要參加': '尚未決定', '活動日期': '2026-02-30', '時間戳記': '2026-10-31T12:00:00'})
        self.assertIsNone(result['is_member'])
        self.assertIsNone(result['will_attend'])
        self.assertEqual(len(result['normalization_errors']), 4)
        self.assertNotIn('尚未決定', str(result['normalization_errors']))

    def test_question_mapping(self):
        with patch.object(settings, 'google_forms_member_column', '你是社員嗎？'):
            self.assertTrue(normalize_fields({'你是社員嗎？': '社員'})['is_member'])
            self.assertIsNone(normalize_fields({'是否為社員': '是'})['is_member'])

    def test_boolean_cells(self):
        result = normalize_fields({'是否為社員': False, '是否要參加': True})
        self.assertIs(result['is_member'], False)
        self.assertIs(result['will_attend'], True)

    def test_google_date_uses_taiwan_calendar_day(self):
        result = normalize_fields({'活動日期': '2026-11-14T16:00:00.000Z'})
        self.assertEqual(result['event_date'], date(2026, 11, 15))
