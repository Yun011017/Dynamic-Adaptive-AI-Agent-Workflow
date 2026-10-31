import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from app.form_sync import FormSyncError, parse_responses, save_responses, validate_url, fetch_table


class FormSyncTests(unittest.TestCase):
    def test_hash_survives_row_and_column_reordering(self):
        first = parse_responses([['time', 'test'], ['2026-10-31', 1], ['2026-10-30', 2]])
        second = parse_responses([['test', 'time'], [2, '2026-10-30'], [1, '2026-10-31']])
        self.assertEqual(first, second[::-1])

    def test_changed_content_has_new_identity(self):
        first = parse_responses([['test'], [1], [1], [2]])
        self.assertEqual(first[0][0], first[1][0])
        self.assertNotEqual(first[0][0], first[2][0])

    def test_empty_rows_and_invalid_tables(self):
        self.assertEqual(parse_responses([['test'], [''], [None]]), [])
        for table in ([], {}, [['a', 'a']], [['']], [['a'], [1, 2]], [['a'], [{}]], [['a'], [float('nan')]]):
            with self.subTest(table=table), self.assertRaises(FormSyncError):
                parse_responses(table)

    def test_url_restriction(self):
        validate_url('https://script.google.com/macros/s/test/exec')
        validate_url('https://script.googleusercontent.com/macros/echo', redirect=True)
        for url in ('https://example.com', 'http://script.google.com/macros/s/test/exec', 'https://script.google.com:bad/macros/s/test/exec'):
            with self.assertRaises(FormSyncError):
                validate_url(url)

    def test_safe_network_error(self):
        with patch('app.form_sync.settings.google_forms_apps_script_url', 'https://script.google.com/macros/s/test/exec'), patch('app.form_sync.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('SECRET')
            with self.assertRaises(FormSyncError) as caught:
                fetch_table()
            self.assertNotIn('SECRET', str(caught.exception))

    def test_invalid_source_id(self):
        rows = parse_responses([['test'], [1], [2]])
        db = MagicMock()
        for source_id in ('', ' ', 'x' * 256):
            with self.assertRaises(FormSyncError):
                save_responses(db, rows, workspace_slug='development', source_id=source_id)
        db.scalar.assert_not_called()
