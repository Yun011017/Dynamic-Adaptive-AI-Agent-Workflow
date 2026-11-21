import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from pydantic import ValidationError

from app.config import settings
from app.form_fields import normalize_fields
from app.form_sources import activity_source_ids
from app.schemas import FormSourceCreate


class FormSourceTests(unittest.TestCase):
    def test_source_validation(self):
        valid = dict(name=' 工作坊 ', goal_id=1, apps_script_url='https://script.google.com/macros/s/example/exec')
        self.assertEqual(FormSourceCreate(**valid).name, '工作坊')
        for changes in ({'name': ' '}, {'goal_id': 0}, {'apps_script_url': 'https://forms.gle/example'},
                        {'apps_script_url': 'http://script.google.com/macros/s/example/exec'},
                        {'apps_script_url': 'https://script.google.com/macros/s/example/exec#duplicate'},
                        {'timezone': 'Invalid/Timezone'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                FormSourceCreate(**{**valid, **changes})

    def test_source_timezone_does_not_mutate_global_settings(self):
        before = settings.google_forms_naive_timezone
        first = normalize_fields({'時間戳記': '2026/11/21 10:30:00'}, naive_timezone='Asia/Taipei')
        second = normalize_fields({'時間戳記': '2026/11/21 10:30:00'}, naive_timezone='UTC')
        self.assertEqual(first['submitted_at'].hour, 2)
        self.assertEqual(second['submitted_at'].hour, 10)
        self.assertEqual(settings.google_forms_naive_timezone, before)

    def test_activity_source_scope_never_falls_back_to_another_activity(self):
        db = MagicMock()
        db.scalars.return_value.all.return_value = [SimpleNamespace(goal_id=1, source_id='activity-1'),
                                                    SimpleNamespace(goal_id=2, source_id='activity-2')]
        self.assertEqual(activity_source_ids(db, 7, 1), ['activity-1'])
        self.assertEqual(activity_source_ids(db, 7, 3), [])
        db.scalars.return_value.all.return_value = []
        self.assertEqual(activity_source_ids(db, 7, 1), [settings.google_forms_source_id])

    def test_worker_only_syncs_enabled_sources_of_selected_activity(self):
        from app.form_sync import sync_once
        registered = [SimpleNamespace(id=1, workspace_id=7, goal_id=10, enabled=True),
                      SimpleNamespace(id=2, workspace_id=7, goal_id=20, enabled=True),
                      SimpleNamespace(id=3, workspace_id=7, goal_id=10, enabled=False)]
        with patch('app.db.SessionLocal') as sessions, patch('app.form_sources.sync_registered_source',
                return_value=dict(read=2, inserted=1, skipped=1)) as sync, patch('app.form_sync.fetch_table') as legacy:
            sessions.return_value.__enter__.return_value.scalars.return_value.all.return_value = registered
            self.assertEqual(sync_once(workspace_id=7, goal_id=10), dict(read=2, inserted=1, skipped=1))
            sync.assert_called_once_with(1, 7)
            legacy.assert_not_called()
            sync.reset_mock()
            self.assertEqual(sync_once(workspace_id=7, goal_id=30), dict(read=0, inserted=0, skipped=0))
            sync.assert_not_called()
