"""Real PostgreSQL integration tests in a disposable schema; never drops public tables."""
import os
import secrets
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import NullPool

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
original = settings.migration_database_url or settings.database_url
# Isolated schemas require startup search_path, which Neon's pooler rejects.
original_url = make_url(original)
if original_url.host and original_url.host.endswith('.neon.tech') and '-pooler.' in original_url.host:
    original = original_url.set(host=original_url.host.replace('-pooler.', '.')).render_as_string(hide_password=False)
SCHEMA = "platform_test_" + secrets.token_hex(8)
test_url = make_url(original).update_query_dict({"options": "-csearch_path=" + SCHEMA}).render_as_string(hide_password=False)
settings.database_url = test_url
settings.migration_database_url = test_url
settings.platform_api_key = "integration-test-key"
settings.platform_workspace_slug = "development"
settings.agent_provider = "local"
settings.agent_model = "deterministic-langgraph"

# Test discovery imports other modules first, so their app.db engine may already
# point at the default database. Rebind it before importing app modules below;
# this suite must always use its own generated PostgreSQL schema.
import app.db as db
db.engine.dispose()
db.engine = db.build_engine(test_url)
db.SessionLocal.configure(bind=db.engine)
from app.db import engine, SessionLocal
from app.agent_worker import process_one_run
from app.main import app
from app.models import AgentRun, AgentRunCheckpoint, ExecutionAction, Workspace, Goal, Strategy, Execution, ExternalEvent, Observation, Member
from app.retry import read_with_retry


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = create_engine(original, poolclass=NullPool, hide_parameters=True)
        with cls.admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        cls.config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(cls.config, "head")
        cls.seed()
        cls.client = TestClient(app)
        cls.headers = {"Authorization": "Bearer integration-test-key"}

    @classmethod
    def seed(cls):
        with engine.begin() as c:
            c.connection.driver_connection.execute((ROOT / "seed.sql").read_text(), prepare=False)

    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        # Only this generated, verified schema is disposable.
        assert SCHEMA.startswith("platform_test_") and len(SCHEMA) == 30
        with cls.admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{SCHEMA}" CASCADE'))
        cls.admin.dispose()

    def test_01_health_and_auth(self):
        self.assertEqual(self.client.get("/health").json()["database"], "connected")
        self.assertEqual(self.client.get("/goals").status_code, 401)
        self.assertEqual(self.client.get("/goals", headers={"Authorization":"Bearer wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/goals", headers=self.headers).status_code, 200)

    def test_02_api_chain_and_duplicate_version(self):
        g = self.client.post("/goals", headers=self.headers, json={"title":"Integration goal"})
        self.assertEqual(g.status_code, 201, g.text)
        s = self.client.post(f"/goals/{g.json()['id']}/strategies", headers=self.headers, json={"version":1,"content":"Draft only"})
        self.assertEqual(s.status_code, 201, s.text)
        e = self.client.post(f"/strategies/{s.json()['id']}/executions", headers=self.headers)
        self.assertEqual(e.status_code, 201, e.text)
        self.assertEqual(e.json()["status"], "QUEUED")
        duplicate = self.client.post(f"/goals/{g.json()['id']}/strategies", headers=self.headers, json={"version":1,"content":"duplicate"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertNotIn("INSERT", duplicate.text)
        self.assertEqual(self.client.get(f"/executions/{e.json()['id']}",headers=self.headers).status_code,200)

    def test_03_tenant_fk_and_role_constraints(self):
        with SessionLocal() as db:
            other = Workspace(slug="other",name="Other")
            db.add(other); db.commit(); db.refresh(other)
            goal = db.query(Goal).first()
            foreign_goal_id = goal.id
            other_id = other.id
            db.add(Strategy(workspace_id=other_id,goal_id=foreign_goal_id,version=1,content="bad"))
            with self.assertRaises(IntegrityError): db.commit()
            db.rollback()
            db.add(Member(workspace_id=other_id,subject_id="bad",role="reviewer"))
            with self.assertRaises(IntegrityError): db.commit()
            db.rollback()
            own_goal=Goal(workspace_id=other_id,title="Other private goal")
            db.add(own_goal);db.commit();db.refresh(own_goal)
            self.assertEqual(self.client.get(f"/goals/{own_goal.id}",headers=self.headers).status_code,404)

    def test_04_seed_is_repeatable(self):
        def counts():
            with engine.connect() as c:
                return [c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in ("workspaces","members","goals","strategies","executions")]
        before=counts();self.seed();self.seed();self.assertEqual(before,counts())

    def test_05_schema_matches_models(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from app.db import Base
        with engine.connect() as c:
            differences=compare_metadata(MigrationContext.configure(c,opts={"compare_type":True}),Base.metadata)
        self.assertEqual(differences,[])

    def test_06_events_and_observations_deduplicate(self):
        with SessionLocal() as db:
            tenant=db.query(Workspace).filter_by(slug="development").one().id
            values=dict(workspace_id=tenant,provider="test",source_account="account",source_object_id="response-1",source_version="v1",event_type="form_response",raw_payload={"synthetic":True})
            event=ExternalEvent(**values);db.add(event);db.commit();db.refresh(event)
            event_id=event.id
            db.add(ExternalEvent(**values))
            with self.assertRaises(IntegrityError): db.commit()
            db.rollback()
            from datetime import datetime, timezone
            metric=dict(workspace_id=tenant,external_event_id=event_id,metric="registrations",value=1,observed_at=datetime.now(timezone.utc))
            db.add(Observation(**metric));db.commit()
            db.add(Observation(**metric))
            with self.assertRaises(IntegrityError): db.commit()
            db.rollback()

    def test_07_db_outage_is_sanitized(self):
        with patch("app.main.engine.connect", side_effect=OperationalError("secret SQL",{},Exception("private driver text"))):
            result=self.client.get("/health")
        self.assertEqual(result.status_code,503)
        self.assertNotIn("private",result.text)
        self.assertIn("X-Request-ID",result.headers)

    def test_08_retry_only_transient_reads(self):
        calls=[]
        def operation():
            calls.append(1)
            if len(calls)<3: raise OperationalError("",{},Exception())
            return "ok"
        self.assertEqual(read_with_retry(operation,sleep=lambda seconds: None),"ok")
        self.assertEqual(len(calls),3)

    def test_09_repeated_migrate(self):
        command.upgrade(self.config,"head")
        with engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),"0014")

    def test_10_agent_run_is_saved_and_scoped(self):
        goal = self.client.post("/goals", headers=self.headers, json={"title": "Improve workshop registrations"}).json()
        response = self.client.post(
            "/agent/runs",
            headers=self.headers,
            json={
                "goal_id": goal["id"],
                "goal": "Improve workshop registrations",
                "context": "Student club event",
                "constraints": {"channel": "instagram"},
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        run = response.json()
        self.assertEqual(run["status"], "PENDING")
        self.assertEqual(run["agent_provider"], "local")
        self.assertIsNone(run["output_payload"])
        with patch("app.agent_worker.sync_once", return_value={"read": 0, "inserted": 0, "skipped": 0}):
            self.assertEqual(process_one_run(run["run_id"]), run["run_id"])
        run = self.client.get(f"/agent/runs/{run['run_id']}", headers=self.headers).json()
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual(run["output_payload"]["goal_id"], goal["id"])
        self.assertIn("strategy_id", run["output_payload"])
        self.assertIn("form_response_ids", run["output_payload"]["data_source"])
        self.assertEqual(run["output_payload"]["form_sync"]["status"], "succeeded")
        self.assertEqual(
            self.client.get(f"/agent/runs/{run['run_id']}", headers=self.headers).status_code,
            200,
        )
        with SessionLocal() as db:
            self.assertEqual(db.query(AgentRun).filter_by(run_id=run["run_id"]).one().status, "COMPLETED")
            phases = [checkpoint.phase for checkpoint in db.query(AgentRunCheckpoint).order_by(AgentRunCheckpoint.sequence).all()]
            self.assertEqual(phases, ["RUNNING", "COMPLETED"])

    def test_10b_completed_legacy_run_can_be_saved_as_strategy(self):
        legacy_run_id = "legacy-" + secrets.token_hex(12)
        with SessionLocal.begin() as db:
            workspace_id = db.query(Workspace).filter_by(slug="development").one().id
            db.add(AgentRun(
                workspace_id=workspace_id,
                run_id=legacy_run_id,
                status="COMPLETED",
                input_payload={
                    "goal": "Legacy workshop goal",
                    "context": "Saved historical context",
                    "constraints": {"channel": "instagram"},
                },
                output_payload={
                    "target_audience": "students",
                    "content_direction": "workshop invitation",
                    "reason": "historical analysis",
                },
            ))
        response = self.client.post(
            f"/agent/runs/{legacy_run_id}/strategies", headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        output = response.json()["output_payload"]
        self.assertIsInstance(output["strategy_id"], int)
        self.assertEqual(output["strategy_version"], 1)
        self.assertEqual(response.json()["input_payload"]["goal_id"], output["goal_id"])
        repeated = self.client.post(
            f"/agent/runs/{legacy_run_id}/strategies", headers=self.headers
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["output_payload"]["strategy_id"], output["strategy_id"])


    def test_official_registration_execution_attribution(self):
        from datetime import datetime, timezone
        from app.models import FormResponse
        from app.form_sync import parse_responses, save_responses, FormSyncError
        from tests.test_registration_import import registration_payload

        with SessionLocal.begin() as db:
            tenant = db.query(Workspace).filter_by(slug='development').one().id
            goal = Goal(workspace_id=tenant, title='Synthetic club A/B registration')
            db.add(goal)
            db.flush()
            strategy = Strategy(workspace_id=tenant, goal_id=goal.id, version=1, content='Synthetic test')
            db.add(strategy)
            db.flush()
            human = Execution(workspace_id=tenant, strategy_id=strategy.id)
            ai = Execution(workspace_id=tenant, strategy_id=strategy.id)
            db.add_all([human, ai])
            db.flush()
            mapping = {'人工': human.id, 'ai': ai.id}
            other = Workspace(slug='registration-other', name='Other registration tenant')
            db.add(other)
            db.flush()
            other_id = other.id

        rows = parse_responses(registration_payload())
        with patch.object(settings, 'google_forms_execution_map', mapping):
            with SessionLocal.begin() as db:
                first = save_responses(db, rows, workspace_slug='development', source_id='club-formal')
            with SessionLocal.begin() as db:
                second = save_responses(db, rows[::-1], workspace_slug='development', source_id='club-formal')
        self.assertEqual(first, dict(read=2, inserted=2, skipped=0))
        self.assertEqual(second, dict(read=2, inserted=0, skipped=2))
        with SessionLocal() as db:
            saved = db.query(FormResponse).filter_by(source_id='club-formal').all()
            self.assertEqual(len(saved), 2)
            for response in saved:
                self.assertEqual(response.execution_id, mapping[response.copy_source])
                self.assertEqual(response.email, 'member@example.test')
                self.assertEqual(response.respondent_name, '測試社員')
                self.assertTrue(response.is_member)
                self.assertTrue(response.will_attend)
                self.assertEqual(response.submitted_at, datetime(2026, 11, 21, 2, 30, tzinfo=timezone.utc))
                event = db.get(ExternalEvent, response.external_event_id)
                self.assertEqual(event.raw_payload['answers']['文案來源'], response.copy_source)

        # Removing configuration cannot erase established attribution.
        with patch.object(settings, 'google_forms_execution_map', {}):
            with SessionLocal.begin() as db:
                save_responses(db, rows, workspace_slug='development', source_id='club-formal')
                save_responses(db, rows, workspace_slug='development', source_id='club-backfill')
        with SessionLocal() as db:
            self.assertTrue(all(row.execution_id is None for row in
                                db.query(FormResponse).filter_by(source_id='club-backfill')))
        with patch.object(settings, 'google_forms_execution_map', mapping):
            with SessionLocal.begin() as db:
                backfilled = save_responses(db, rows, workspace_slug='development', source_id='club-backfill')
            self.assertEqual(backfilled, dict(read=2, inserted=0, skipped=2))
        with SessionLocal() as db:
            backfilled_rows = db.query(FormResponse).filter_by(source_id='club-backfill').all()
            self.assertEqual(len(backfilled_rows), 2)
            for row in backfilled_rows:
                self.assertEqual(row.execution_id, mapping[row.copy_source])
        with patch.object(settings, 'google_forms_execution_map', {'人工': mapping['ai']}):
            with self.assertRaises(FormSyncError), SessionLocal.begin() as db:
                save_responses(db, rows, workspace_slug='development', source_id='club-formal')
        with patch.object(settings, 'google_forms_execution_map', mapping):
            with self.assertRaises(FormSyncError), SessionLocal.begin() as db:
                save_responses(db, rows, workspace_slug='registration-other', source_id='club-cross')
        # Database constraint also rejects a cross-tenant link without the importer.
        with self.assertRaises(IntegrityError), SessionLocal.begin() as db:
            event = ExternalEvent(workspace_id=other_id, provider='test', source_account='cross',
                                  source_object_id='cross', source_version='v1', event_type='form_response', raw_payload={})
            db.add(event)
            db.flush()
            db.add(FormResponse(workspace_id=other_id, external_event_id=event.id,
                                source_id='cross', execution_id=mapping['ai']))
            db.flush()
        with SessionLocal() as db:
            self.assertEqual(db.query(FormResponse).filter_by(source_id='club-cross').count(), 0)
            for response in db.query(FormResponse).filter_by(source_id='club-formal'):
                self.assertEqual(response.execution_id, mapping[response.copy_source])

    def test_form_binding_api_backfills_and_controls_future_imports(self):
        from app.models import FormResponse, FormExecutionBinding
        from app.form_sync import parse_responses, save_responses
        from tests.test_registration_import import registration_payload
        with SessionLocal.begin() as db:
            tenant = db.query(Workspace).filter_by(slug='development').one().id
            goal = Goal(workspace_id=tenant, title='UI form binding test')
            db.add(goal)
            db.flush()
            strategy = Strategy(workspace_id=tenant, goal_id=goal.id, version=1, content='UI attribution')
            db.add(strategy)
            db.flush()
            first = Execution(workspace_id=tenant, strategy_id=strategy.id)
            second = Execution(workspace_id=tenant, strategy_id=strategy.id)
            db.add_all([first, second])
            db.flush()
            execution_id, other_id, strategy_id = first.id, second.id, strategy.id
        payload = registration_payload()
        with patch.object(settings, 'google_forms_execution_map', {}):
            with SessionLocal.begin() as db:
                save_responses(db, parse_responses(payload), workspace_slug='development', source_id='ui-form-source')
        self.assertEqual(self.client.get('/form-sources').status_code, 401)
        listed = self.client.get('/form-sources', headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn('member@example.test', listed.text)
        self.assertNotIn('測試社員', listed.text)
        executions = self.client.get(f'/strategies/{strategy_id}/executions', headers=self.headers).json()
        self.assertEqual({row['id'] for row in executions}, {execution_id, other_id})
        binding = dict(source_id='ui-form-source', copy_source='人工')
        path = f'/executions/{execution_id}/form-bindings'
        result = self.client.post(path, headers=self.headers, json=binding)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['backfilled'], 1)
        repeated = self.client.post(path, headers=self.headers, json=binding)
        self.assertEqual(repeated.json()['backfilled'], 0)
        conflict = self.client.post(f'/executions/{other_id}/form-bindings', headers=self.headers, json=binding)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.post(path, headers=self.headers, json={**binding, 'source_id': 'missing'}).status_code, 404)
        self.assertEqual(self.client.post(path, headers=self.headers, json={**binding, 'copy_source': 'unknown'}).status_code, 422)
        self.assertEqual(self.client.post(path, headers=self.headers, json={**binding, 'source_id': '  '}).status_code, 422)
        self.assertEqual(self.client.post('/executions/999999999/form-bindings', headers=self.headers, json=binding).status_code, 404)
        # Later responses use DB binding even if the old env mapping differs.
        payload['data']['人工'].append({**payload['data']['人工'][0], '時間戳記': '2026-11-21T11:30:00+08:00'})
        with patch.object(settings, 'google_forms_execution_map', {'人工': other_id}):
            with SessionLocal.begin() as db:
                saved = save_responses(db, parse_responses(payload), workspace_slug='development', source_id='ui-form-source')
        self.assertEqual(saved, dict(read=3, inserted=1, skipped=2))
        with SessionLocal() as db:
            rows = db.query(FormResponse).filter_by(source_id='ui-form-source').all()
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertEqual(row.execution_id, execution_id if row.copy_source == '人工' else None)
            self.assertEqual(db.query(FormExecutionBinding).filter_by(source_id='ui-form-source').count(), 1)
        with SessionLocal.begin() as db:
            other = Workspace(slug='ui-binding-other', name='Isolated UI tenant')
            db.add(other)
        with patch.object(settings, 'platform_workspace_slug', 'ui-binding-other'):
            self.assertEqual(self.client.post(path, headers=self.headers, json=binding).status_code, 404)
            self.assertNotIn('ui-form-source', self.client.get('/form-sources', headers=self.headers).text)

    def test_z_registered_form_sources_are_activity_scoped(self):
        from app.models import FormResponse, FormSource
        from app.form_summary import get_form_summary
        from app.form_sync import FormSyncError, sync_once
        from tests.test_registration_import import registration_payload
        with SessionLocal.begin() as db:
            tenant = db.query(Workspace).filter_by(slug='development').one().id
            goals = [Goal(workspace_id=tenant, title='Source activity A'), Goal(workspace_id=tenant, title='Source activity B')]
            db.add_all(goals)
            db.flush()
            goal_a, goal_b = [goal.id for goal in goals]
            strategies = [Strategy(workspace_id=tenant, goal_id=goal.id, version=1, content='source registry') for goal in goals]
            db.add_all(strategies)
            db.flush()
            executions = [Execution(workspace_id=tenant, strategy_id=strategy.id) for strategy in strategies]
            db.add_all(executions)
            db.flush()
            execution_a, execution_b = [execution.id for execution in executions]
            other = Workspace(slug='source-registry-other', name='Other source workspace')
            db.add(other)
        endpoint_a = 'https://script.google.com/macros/s/source-a/exec?token=private-token'
        endpoint_b = 'https://script.google.com/macros/s/source-b/exec'
        def create(name, goal, url):
            return self.client.post('/form-source-configs', headers=self.headers,
                                    json=dict(name=name, goal_id=goal, apps_script_url=url, timezone='Asia/Taipei'))
        self.assertEqual(self.client.get('/form-source-configs').status_code, 401)
        self.assertEqual(create('bad', goal_a, 'https://forms.gle/test').status_code, 422)
        self.assertEqual(create('missing', 999999999, endpoint_a).status_code, 404)
        created_a = create('Activity A forms', goal_a, endpoint_a)
        self.assertEqual(created_a.status_code, 201, created_a.text)
        created_b = create('Activity B forms', goal_b, endpoint_b)
        self.assertEqual(created_b.status_code, 201, created_b.text)
        a, b = created_a.json(), created_b.json()
        self.assertNotIn('private-token', created_a.text)
        self.assertNotEqual(a['source_id'], b['source_id'])
        self.assertEqual(create('duplicate', goal_b, endpoint_a).status_code, 409)
        listed = self.client.get('/form-sources', headers=self.headers).json()
        self.assertEqual(len([row for row in listed if row.get('source_id') == a['source_id']]), 2)
        # Sources can be bound before any response exists, but only within their activity.
        binding = dict(source_id=a['source_id'], copy_source='人工')
        self.assertEqual(self.client.post(f'/executions/{execution_b}/form-bindings', headers=self.headers, json=binding).status_code, 409)
        self.assertEqual(self.client.post(f'/executions/{execution_a}/form-bindings', headers=self.headers, json=binding).status_code, 200)
        payload = registration_payload()
        for rows in payload['data'].values():
            rows[0]['時間戳記'] = '2026/11/21 上午 10:30:00'
        path_a, path_b = f"/form-source-configs/{a['id']}", f"/form-source-configs/{b['id']}"
        with patch('app.form_sync.fetch_table', return_value=payload) as fetch:
            result = self.client.post(path_a + '/sync', headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json(), dict(read=2, inserted=2, skipped=0))
            fetch.assert_called_once_with(endpoint_a)
            self.assertEqual(self.client.post(path_a + '/sync', headers=self.headers).json()['inserted'], 0)
            self.assertEqual(self.client.post(path_b + '/sync', headers=self.headers).json()['inserted'], 2)
        with SessionLocal() as db:
            saved = db.query(FormResponse).filter_by(source_id=a['source_id']).all()
            self.assertEqual(len(saved), 2)
            for row in saved:
                self.assertEqual(row.submitted_at.hour, 2)
                self.assertEqual(row.execution_id, execution_a if row.copy_source == '人工' else None)
        self.assertEqual(get_form_summary(workspace_id=tenant, goal_id=goal_a)['response_count'], 2)
        self.assertEqual(get_form_summary(workspace_id=tenant, goal_id=goal_b)['response_count'], 2)
        self.assertEqual(get_form_summary(workspace_id=tenant, goal_id=999999999)['response_count'], 0)
        from app.agent_worker import load_strategy_context
        with SessionLocal() as db:
            _, refs = load_strategy_context(db, workspace_id=tenant, goal_id=goal_a)
            self.assertEqual(len(refs['form_response_ids']), 2)
        # Legacy imports that already point at another activity cannot be adopted.
        with patch.object(settings, 'google_forms_apps_script_url', 'https://script.google.com/macros/s/legacy-linked/exec'), \
             patch.object(settings, 'google_forms_source_id', a['source_id']):
            self.assertEqual(create('Wrong activity', goal_b, settings.google_forms_apps_script_url).status_code, 409)
        # Google failures are sanitized and leave previously saved responses intact.
        with patch('app.form_sync.fetch_table', side_effect=FormSyncError('Cannot read Apps Script')):
            self.assertEqual(self.client.post(path_a + '/sync', headers=self.headers).status_code, 502)
        self.assertEqual(get_form_summary(workspace_id=tenant, goal_id=goal_a)['response_count'], 2)
        self.assertEqual(self.client.patch(path_b, headers=self.headers, json={'enabled': False}).status_code, 200)
        self.assertEqual(self.client.post(path_b + '/sync', headers=self.headers).status_code, 409)
        with patch('app.form_sources.sync_registered_source', return_value=dict(read=2, inserted=0, skipped=2)) as sync:
            self.assertEqual(sync_once(workspace_id=tenant, goal_id=goal_a)['read'], 2)
            sync.assert_called_once_with(a['id'], tenant)
            sync.reset_mock()
            self.assertEqual(sync_once(workspace_id=tenant, goal_id=goal_b)['read'], 0)
            sync.assert_not_called()
        self.assertEqual(self.client.patch(path_b, headers=self.headers, json={'enabled': True}).status_code, 200)
        # Adopting the original .env URL retains its identity instead of importing duplicates.
        with patch.object(settings, 'google_forms_apps_script_url', 'https://script.google.com/macros/s/adopt/exec'), \
             patch.object(settings, 'google_forms_source_id', 'adopt-existing'):
            adopted = create('Adopt legacy', goal_a, settings.google_forms_apps_script_url)
            self.assertEqual(adopted.status_code, 201, adopted.text)
            self.assertEqual(adopted.json()['source_id'], 'adopt-existing')
        with patch.object(settings, 'platform_workspace_slug', 'source-registry-other'):
            self.assertEqual(self.client.get('/form-source-configs', headers=self.headers).json(), [])
            self.assertEqual(self.client.post(path_a + '/sync', headers=self.headers).status_code, 404)
            self.assertEqual(self.client.patch(path_a, headers=self.headers, json={'enabled': False}).status_code, 404)
            self.assertEqual(create('foreign activity', goal_a, endpoint_a).status_code, 404)

    def test_11_form_ingestion_is_idempotent(self):
        from app.form_sync import parse_responses, save_responses, PROVIDER
        rows = parse_responses([['時間戳記', 'test', 'temp'], ['2026-10-31T00:00:00Z', 1, 2], ['2026-10-31T01:00:00Z', 3, 4]])
        with SessionLocal.begin() as db:
            first = save_responses(db, rows, workspace_slug='development', source_id='integration-form')
        with SessionLocal.begin() as db:
            second = save_responses(db, rows[::-1], workspace_slug='development', source_id='integration-form')
        self.assertEqual(first, dict(read=2, inserted=2, skipped=0))
        self.assertEqual(second, dict(read=2, inserted=0, skipped=2))
        with SessionLocal() as db:
            self.assertEqual(db.query(ExternalEvent).filter_by(provider=PROVIDER, source_account='integration-form').count(), 2)

    def test_12_form_summary_is_scoped_and_used_by_agent(self):
        from app.form_summary import get_form_summary
        from app.form_sync import parse_responses, save_responses
        from app.agent_runner import run_agent
        rows = parse_responses([['test', 'temp', 'Email'], [1, 2, 'private@example.test'], [3, 4, 'other@example.test']])
        with SessionLocal.begin() as db:
            save_responses(db, rows, workspace_slug='development', source_id='summary-integration')
            save_responses(db, rows, workspace_slug='development', source_id='other-form')
            other = Workspace(slug='summary-empty', name='Other workspace')
            db.add(other)
            db.flush()
            other_id = other.id
        with patch.object(settings, 'google_forms_source_id', 'summary-integration'):
            summary = get_form_summary()
            self.assertEqual(summary['response_count'], 2)
            self.assertEqual(summary['storage_table'], 'form_responses')
            self.assertEqual(summary['membership'], dict(yes=0, no=0, unknown=2))
            self.assertNotIn('Email', str(summary))
            self.assertEqual(get_form_summary(workspace_id=other_id)['response_count'], 0)
            self.assertEqual(run_agent(goal='test', context='', constraints={})['form_summary'], summary)


    def test_13_structured_fields_are_saved_and_remapped(self):
        from app.form_sync import parse_responses, save_responses
        from app.models import FormResponse
        rows = parse_responses([['是否是社員', '是否要參加', '學校', '系級', '參加的活動', '時間戳記'],
                                ['是', '不參加', '臺大', '資工二', '物聯網工作坊', '2026-10-31T00:00:00Z']])
        with SessionLocal.begin() as db:
            first = save_responses(db, rows, workspace_slug='development', source_id='structured-test')
        with SessionLocal.begin() as db:
            second = save_responses(db, rows, workspace_slug='development', source_id='structured-test')
        self.assertEqual(first['inserted'], 1)
        self.assertEqual(second['inserted'], 0)
        with SessionLocal() as db:
            result = db.query(FormResponse).filter_by(source_id='structured-test').one()
            self.assertTrue(result.is_member)
            self.assertFalse(result.will_attend)
            self.assertEqual(result.school, '臺大')
            self.assertEqual(result.department_grade, '資工二')
            self.assertEqual(result.activity_name, '物聯網工作坊')
            self.assertIsNotNone(result.submitted_at)
        from app.form_summary import get_form_summary
        with patch.object(settings, 'google_forms_source_id', 'structured-test'):
            summary = get_form_summary()
            self.assertEqual(summary['membership']['yes'], 1)
            self.assertEqual(summary['attendance']['no'], 1)
            self.assertEqual(summary['activities'], {'物聯網工作坊': 1})
            self.assertEqual(summary['schools'], {'臺大': 1})
            self.assertEqual(summary['department_grades'], {'資工二': 1})
        # A remapping of existing source data refreshes typed fields without duplicating raw events.
        with patch.object(settings, 'google_forms_member_column', 'missing'):
            with SessionLocal.begin() as db:
                save_responses(db, rows, workspace_slug='development', source_id='structured-test')
        with SessionLocal() as db:
            self.assertIsNone(db.query(FormResponse).filter_by(source_id='structured-test').one().is_member)


    def test_14_sync_write_failure_rolls_back_and_agent_uses_saved_data(self):
        from app.form_sync import parse_responses, save_responses, PROVIDER
        from app.models import FormResponse
        original_save = save_responses
        rows = parse_responses([['test'], [1], [2]])
        with SessionLocal.begin() as db:
            save_responses(db, rows, workspace_slug='development', source_id='fallback-integration')
        def fail_after_writes(db, responses, **kwargs):
            original_save(db, responses, **kwargs)
            raise RuntimeError('SECRET simulated DB failure')
        with patch.object(settings, 'google_forms_source_id', 'fallback-integration'):
            goal = self.client.post('/goals', headers=self.headers, json={'title': 'Verify sync fallback'}).json()
            response = self.client.post('/agent/runs', headers=self.headers, json={'goal_id': goal['id'], 'goal': 'Verify sync fallback'})
            self.assertEqual(response.status_code, 202)
            run_id = response.json()['run_id']
            with patch('app.form_sync.fetch_table', return_value=[['test'], [1], [2], [3]]), patch('app.form_sync.save_responses', side_effect=fail_after_writes):
                self.assertEqual(process_one_run(run_id), run_id)
            result = self.client.get(f'/agent/runs/{run_id}', headers=self.headers).json()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['output_payload']['form_summary']['response_count'], 2)
        self.assertTrue(result['output_payload']['form_sync']['fallback_used'])
        self.assertNotIn('SECRET', str(result['output_payload']))
        with SessionLocal() as db:
            self.assertEqual(db.query(ExternalEvent).filter_by(provider=PROVIDER, source_account='fallback-integration').count(), 2)
            self.assertEqual(db.query(FormResponse).filter_by(source_id='fallback-integration').count(), 2)

    def test_15_content_drafts_are_versioned_scheduled_and_idempotent(self):
        goal = self.client.post("/goals", headers=self.headers, json={"title": "Draft integration goal"}).json()
        strategy = self.client.post(
            f"/goals/{goal['id']}/strategies",
            headers=self.headers,
            json={"version": 1, "content": "Show hands-on projects"},
        ).json()
        payload = {
            "channel": "instagram",
            "caption": "Build your first project with us",
            "hashtags": ["NTUMaker", "Arduino", "NTUMaker"],
            "image_requirements": ["1080 by 1080 cover showing a student project"],
            "image_urls": ["https://images.example.test/cover.jpg"],
            "scheduled_at": "2030-01-02T18:30:00+08:00",
            "schedule_requested": True,
        }
        created = self.client.post(
            f"/strategies/{strategy['id']}/content-drafts", headers=self.headers, json=payload
        )
        self.assertEqual(created.status_code, 201, created.text)
        draft = created.json()
        self.assertEqual(draft["status"], "SCHEDULED")
        self.assertEqual(draft["draft_version"], 1)
        self.assertEqual(draft["payload"]["hashtags"], ["NTUMaker", "Arduino"])
        self.assertEqual(draft["payload"]["meta_adapter_payload"]["caption"], "Build your first project with us\n\n#NTUMaker #Arduino")
        duplicate = self.client.post(
            f"/strategies/{strategy['id']}/content-drafts", headers=self.headers, json=payload
        )
        self.assertEqual(duplicate.status_code, 201, duplicate.text)
        self.assertEqual(duplicate.json()["id"], draft["id"])
        revised = self.client.post(
            f"/content-drafts/{draft['id']}/versions",
            headers=self.headers,
            json={**payload, "caption": "Build something real with us", "scheduled_at": None, "schedule_requested": False},
        )
        self.assertEqual(revised.status_code, 201, revised.text)
        self.assertEqual(revised.json()["draft_version"], 2)
        self.assertEqual(revised.json()["status"], "DRAFT")
        with SessionLocal() as db:
            previous = db.get(ExecutionAction, draft["id"])
            self.assertEqual(previous.status, "SUPERSEDED")
            self.assertEqual(db.query(Execution).filter_by(strategy_id=strategy["id"]).count(), 1)

    def test_16_latest_strategy_includes_same_goal_draft_history(self):
        goal = self.client.post(
            "/goals", headers=self.headers, json={"title": "Shared draft history goal"}
        ).json()
        first_strategy = self.client.post(
            f"/goals/{goal['id']}/strategies",
            headers=self.headers,
            json={"version": 1, "content": "First direction"},
        ).json()
        draft = self.client.post(
            f"/strategies/{first_strategy['id']}/content-drafts",
            headers=self.headers,
            json={
                "channel": "instagram",
                "caption": "A saved proposal from the first strategy version",
                "image_requirements": ["cover"],
                "image_urls": ["https://images.example.test/cover.jpg"],
            },
        )
        self.assertEqual(draft.status_code, 201, draft.text)
        latest_strategy = self.client.post(
            f"/goals/{goal['id']}/strategies",
            headers=self.headers,
            json={"version": 2, "content": "Second direction"},
        ).json()

        listed = self.client.get(
            f"/strategies/{latest_strategy['id']}/content-drafts",
            headers=self.headers,
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()], [draft.json()["id"]])

    def test_17_strategy_regeneration_versions_and_draft_links(self):
        goal = self.client.post(
            "/goals", headers=self.headers, json={"title": "Versioned strategy goal"}
        ).json()

        def create_run():
            return self.client.post(
                "/agent/runs",
                headers=self.headers,
                json={
                    "goal_id": goal["id"],
                    "goal": goal["title"],
                    "context": "Keep the same campaign context",
                    "constraints": {"channel": "instagram"},
                },
            ).json()

        first_run = create_run()
        self.assertEqual(process_one_run(first_run["run_id"]), first_run["run_id"])
        first = self.client.get(
            f"/agent/runs/{first_run['run_id']}", headers=self.headers
        ).json()
        first_strategy_id = first["output_payload"]["strategy_id"]
        first_content_run_id = self.client.post(
            f"/strategies/{first_strategy_id}/content-draft-runs",
            headers=self.headers,
            json={"channel": "instagram", "content_format": "carousel"},
        ).json()["run_id"]
        self.assertEqual(process_one_run(first_content_run_id), first_content_run_id)

        second_run = create_run()
        self.assertEqual(process_one_run(second_run["run_id"]), second_run["run_id"])
        second = self.client.get(
            f"/agent/runs/{second_run['run_id']}", headers=self.headers
        ).json()
        second_strategy_id = second["output_payload"]["strategy_id"]
        second_content_run_id = self.client.post(
            f"/strategies/{second_strategy_id}/content-draft-runs",
            headers=self.headers,
            json={"channel": "instagram", "content_format": "carousel"},
        ).json()["run_id"]
        self.assertEqual(process_one_run(second_content_run_id), second_content_run_id)

        self.assertNotEqual(first_strategy_id, second_strategy_id)
        self.assertEqual(first["output_payload"]["strategy_version"], 1)
        self.assertEqual(second["output_payload"]["strategy_version"], 2)
        with SessionLocal() as db:
            actions = (
                db.query(ExecutionAction)
                .join(Execution, Execution.id == ExecutionAction.execution_id)
                .filter(Execution.strategy_id.in_([first_strategy_id, second_strategy_id]))
                .all()
            )
            self.assertEqual(
                {action.payload["strategy_id"] for action in actions},
                {first_strategy_id, second_strategy_id},
            )


if __name__ == "__main__":
    unittest.main()
