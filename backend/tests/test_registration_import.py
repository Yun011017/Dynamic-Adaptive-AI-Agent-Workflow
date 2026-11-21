"""Official club registration contract, using synthetic personal information."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import settings
from app.form_fields import normalize_fields
from app.form_sync import FormSyncError, parse_responses, save_responses


def registration_payload():
    row = {'時間戳記': '2026-11-21T10:30:00+08:00',
           '電子郵件地址': 'member@example.test', '姓名': '測試社員', '是否是社員': '是'}
    return {'success': True, 'data': {'人工': [dict(row)], 'ai': [dict(row)]}}


class RegistrationImportTests(unittest.TestCase):
    def setUp(self):
        for name, value in {
            'google_forms_member_column': '是否是社員',
            'google_forms_email_column': '電子郵件地址',
            'google_forms_name_column': '姓名',
            'google_forms_source_column': '文案來源',
            'google_forms_submitted_at_column': '時間戳記',
            'google_forms_naive_timezone': '',
            'google_forms_execution_map': {'人工': 101, 'ai': 102},
        }.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_official_fields_and_sources(self):
        rows = parse_responses(registration_payload())
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][0], rows[1][0])
        for (_, answers), source in zip(rows, ['人工', 'ai']):
            fields = normalize_fields(answers)
            self.assertEqual(fields['email'], 'member@example.test')
            self.assertEqual(fields['respondent_name'], '測試社員')
            self.assertEqual(fields['copy_source'], source)
            self.assertTrue(fields['is_member'])
            self.assertIs(fields['will_attend'], True)
            self.assertIsNone(fields['activity_name'])
            self.assertEqual(fields['submitted_at'], datetime(2026, 11, 21, 2, 30, tzinfo=timezone.utc))
            self.assertEqual(fields['normalization_errors'], [])

    def test_reordering_groups_and_fields_preserves_identity(self):
        payload = registration_payload()
        first = parse_responses(payload)
        payload['data'] = {key: [dict(reversed(list(row.items()))) for row in rows]
                           for key, rows in reversed(list(payload['data'].items()))}
        self.assertEqual(first, parse_responses(payload)[::-1])

    def test_empty_forms(self):
        self.assertEqual(parse_responses({'success': True, 'data': {'人工': [], 'ai': []}}), [])

    def test_invalid_envelopes_and_sources_fail_closed(self):
        for payload in (
            {'success': False, 'error': 'private'},
            {'success': True, 'data': {'other': []}},
            {'success': True, 'data': {'ai': {}}},
            {'success': True, 'data': {'ai': [[]]}},
            {'success': True, 'data': {'ai': [{'文案來源': '人工'}]}},
            {'success': True, 'data': {'ai': [{'姓名': {'invalid': 1}}]}},
        ):
            with self.subTest(payload=payload), self.assertRaises(FormSyncError):
                parse_responses(payload)

    def test_timezone_less_sheet_timestamp_requires_explicit_timezone(self):
        answers = {'時間戳記': '2026/11/21 10:30:00'}
        self.assertIsNone(normalize_fields(answers)['submitted_at'])
        with patch.object(settings, 'google_forms_naive_timezone', 'Asia/Taipei'):
            self.assertEqual(normalize_fields(answers)['submitted_at'],
                             datetime(2026, 11, 21, 2, 30, tzinfo=timezone.utc))

    def test_member_values_and_missing_personal_fields(self):
        for value, expected in [('是', True), ('否', False), ('尚未決定', None), ('', None)]:
            with self.subTest(value=value):
                result = normalize_fields({'是否是社員': value})
                self.assertIs(result['is_member'], expected)
                self.assertIsNone(result['email'])
                self.assertIsNone(result['respondent_name'])

    def test_real_sheet_chinese_timestamp_and_noon_boundaries(self):
        with patch.object(settings, 'google_forms_naive_timezone', 'Asia/Taipei'):
            for period, hour, expected_hour in [('上午', 3, 19), ('上午', 12, 16),
                                                 ('下午', 12, 4), ('下午', 3, 7)]:
                with self.subTest(period=period, hour=hour):
                    result = normalize_fields({'時間戳記': f'2026/11/21 {period} {hour}:28:51'})
                    self.assertEqual(result['submitted_at'].hour, expected_hour)
                    self.assertEqual(result['submitted_at'].day, 20 if period == '上午' else 21)
                    self.assertEqual(result['normalization_errors'], [])
            self.assertIsNone(normalize_fields({'時間戳記': '2026/11/21 下午 13:28:51'})['submitted_at'])
        self.assertIsNone(normalize_fields({'時間戳記': '2026/11/21 上午 3:28:51'})['submitted_at'])

    def test_unknown_source_and_invalid_date_do_not_leak_answers(self):
        result = normalize_fields({'文案來源': 'private-source', '時間戳記': 'private-date',
                                   '電子郵件地址': 123, '姓名': 'x' * 256})
        self.assertIsNone(result['copy_source'])
        self.assertIsNone(result['submitted_at'])
        self.assertIsNone(result['email'])
        self.assertIsNone(result['respondent_name'])
        self.assertNotIn('private', str(result['normalization_errors']))

    def test_invalid_or_cross_workspace_execution_rejected_before_writes(self):
        rows = parse_responses(registration_payload())
        db = MagicMock()
        db.scalar.side_effect = [1, None]
        with self.assertRaisesRegex(FormSyncError, 'workspace'):
            save_responses(db, rows, workspace_slug='development', source_id='club-ab')
        self.assertEqual(db.scalar.call_count, 2)
        db.execute.assert_not_called()

    def test_existing_attribution_cannot_be_changed(self):
        rows = parse_responses(registration_payload())[:1]
        db = MagicMock()
        # Conditional upsert returns no row when another execution is already linked.
        db.scalar.side_effect = [1, 101, 11, None]
        with self.assertRaisesRegex(FormSyncError, 'reassigned'):
            save_responses(db, rows, workspace_slug='development', source_id='club-ab')
