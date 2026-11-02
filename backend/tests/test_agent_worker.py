import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.schemas import ContentDraftCreate


class AgentWorkerTests(unittest.TestCase):
    def setUp(self):
        # Import only when running tests, so discovery can configure an isolated DB first.
        from app import agent_worker
        self.worker = agent_worker

    def process(self, *, sync_error=None, response_count=3, agent_error=None):
        row = SimpleNamespace(id=1, run_id='test-run', workspace_id=7, agent_provider='local',
                              agent_model='deterministic-langgraph', input_payload={'goal': 'test'},
                              attempts=1, output_payload=None, error_code=None, status='RUNNING')
        sequence = []
        def sync(**kwargs):
            self.assertEqual(kwargs, {'workspace_id': 7})
            sequence.append('sync')
            if sync_error:
                raise sync_error
            return dict(read=response_count, inserted=1, skipped=max(0, response_count - 1))
        def agent(**kwargs):
            self.assertEqual(kwargs['workspace_id'], 7)
            sequence.append('agent')
            if agent_error:
                raise agent_error
            return dict(reason='analysis', form_summary={'response_count': response_count})
        with patch.object(self.worker, 'SessionLocal') as session, patch.object(self.worker, 'claim_next_run', return_value=row), patch.object(self.worker, 'checkpoint') as checkpoint, patch.object(self.worker, 'sync_once', side_effect=sync), patch.object(self.worker, 'run_agent', side_effect=agent):
            session.return_value.__enter__.return_value = MagicMock()
            self.assertEqual(self.worker.process_one_run(), 'test-run')
        self.assertEqual(sequence, ['sync', 'agent'])
        return row, checkpoint

    def test_sync_precedes_analysis(self):
        row, _ = self.process()
        self.assertEqual(row.status, 'COMPLETED')
        self.assertEqual(row.output_payload['form_sync']['status'], 'succeeded')
        self.assertFalse(row.output_payload['form_sync']['fallback_used'])

    def test_sync_failure_uses_saved_data_and_masks_error(self):
        row, checkpoint = self.process(sync_error=RuntimeError('SECRET raw response / SQL'))
        self.assertEqual(row.status, 'COMPLETED')
        self.assertTrue(row.output_payload['form_sync']['fallback_used'])
        self.assertEqual(row.output_payload['form_summary']['response_count'], 3)
        self.assertIn('沿用', row.output_payload['reason'])
        self.assertNotIn('SECRET', json.dumps(row.output_payload))
        self.assertEqual(checkpoint.call_args.args[3]['form_sync']['status'], 'failed')

    def test_no_saved_data_reports_insufficient_data(self):
        row, _ = self.process(sync_error=TimeoutError(), response_count=0)
        self.assertEqual(row.status, 'COMPLETED')
        self.assertFalse(row.output_payload['form_sync']['fallback_used'])
        self.assertIn('資料不足', row.output_payload['reason'])

    def test_agent_failure_is_still_a_failed_run(self):
        row, _ = self.process(sync_error=TimeoutError(), agent_error=RuntimeError('DB down'))
        self.assertEqual(row.status, 'FAILED')
        self.assertIsNone(row.output_payload)

    def test_no_queued_work_does_not_poll_forms(self):
        with patch.object(self.worker, 'SessionLocal'), patch.object(self.worker, 'claim_next_run', return_value=None), patch.object(self.worker, 'sync_once') as sync:
            self.assertIsNone(self.worker.process_one_run())
            sync.assert_not_called()

    def test_failed_write_exits_sync_transaction_with_error(self):
        from app.form_sync import sync_once
        error = RuntimeError('injected write failure')
        with patch('app.db.SessionLocal') as session, patch('app.form_sync.fetch_table', return_value=[['test'], [1]]), patch('app.form_sync.save_responses', side_effect=error):
            transaction = session.begin.return_value
            transaction.__exit__.return_value = False
            with self.assertRaises(RuntimeError):
                sync_once()
            self.assertIs(transaction.__exit__.call_args.args[1], error)

    def test_other_workspace_does_not_import_configured_source(self):
        from app.form_sync import sync_once, FormSyncError
        with patch('app.db.SessionLocal') as session, patch('app.form_sync.fetch_table', return_value=[['test'], [1]]), patch('app.form_sync.save_responses') as save:
            session.begin.return_value.__enter__.return_value.scalar.return_value = None
            with self.assertRaises(FormSyncError):
                sync_once(workspace_id=999)
            save.assert_not_called()

    def test_content_draft_job_uses_persisted_strategy_and_never_syncs_forms(self):
        row = SimpleNamespace(
            workspace_id=7,
            agent_provider="local",
            agent_model="deterministic-langgraph",
            input_payload={"job_type": "CONTENT_DRAFT", "strategy_id": 12, "channel": "instagram", "scheduled_at": None},
        )
        strategy = SimpleNamespace(id=12, version=1, goal_id=3, workspace_id=7)
        goal = SimpleNamespace(id=3, workspace_id=7)
        action = SimpleNamespace(id=44, payload={"carousel": True, "caption": "草稿"})
        db = MagicMock()
        db.scalar.side_effect = [strategy, goal]
        with patch.object(self.worker, "generate_content_draft", return_value=ContentDraftCreate(
            caption="草稿", carousel=True, image_requirements=["封面", "作品照"]
        )) as generate, patch.object(self.worker, "create_content_draft", return_value=(action, True)) as save:
            output = self.worker.create_generated_content_draft(db, row)
        generate.assert_called_once()
        save.assert_called_once()
        self.assertEqual(output["content_draft_action_id"], 44)
        self.assertTrue(output["content_draft"]["carousel"])

    def test_strategy_result_automatically_queues_content_draft_work(self):
        row = SimpleNamespace(
            id=1, run_id="strategy-run", workspace_id=7, agent_provider="local",
            agent_model="deterministic-langgraph", input_payload={"goal": "test"},
            attempts=1, output_payload=None, error_code=None, status="RUNNING",
        )
        queued = SimpleNamespace(run_id="content-run")
        with patch.object(self.worker, "SessionLocal") as session, \
             patch.object(self.worker, "claim_next_run", return_value=row), \
             patch.object(self.worker, "checkpoint"), \
             patch.object(self.worker, "sync_once", return_value={"read": 0, "inserted": 0, "skipped": 0}), \
             patch.object(self.worker, "run_agent", return_value={"strategy_id": 12, "reason": "strategy"}), \
             patch.object(self.worker, "queue_content_draft_run", return_value=queued) as queue:
            session.return_value.__enter__.return_value = MagicMock()
            self.assertEqual(self.worker.process_one_run(), "strategy-run")
        self.assertEqual(row.status, "COMPLETED")
        self.assertEqual(row.output_payload["content_draft_run_id"], "content-run")
        queue.assert_called_once_with(
            session.return_value.__enter__.return_value,
            workspace_id=7,
            strategy_id=12,
            provider="local",
            model_name="deterministic-langgraph",
        )
