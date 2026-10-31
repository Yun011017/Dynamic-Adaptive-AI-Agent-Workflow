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
SCHEMA = "platform_test_" + secrets.token_hex(8)
test_url = make_url(original).update_query_dict({"options": "-csearch_path=" + SCHEMA}).render_as_string(hide_password=False)
settings.database_url = test_url
settings.migration_database_url = test_url
settings.platform_api_key = "integration-test-key"
settings.platform_workspace_slug = "development"

from app.db import engine, SessionLocal
from app.agent_worker import process_one_run
from app.main import app
from app.models import AgentRun, AgentRunCheckpoint, Workspace, Goal, Strategy, Execution, ExternalEvent, Observation, Member
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
            self.assertEqual(c.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),"0004")

    def test_10_agent_run_is_saved_and_scoped(self):
        response = self.client.post(
            "/agent/runs",
            headers=self.headers,
            json={
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
        self.assertEqual(process_one_run(), run["run_id"])
        run = self.client.get(f"/agent/runs/{run['run_id']}", headers=self.headers).json()
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual(run["output_payload"]["data_source"], "neon_form_summary")
        self.assertEqual(
            self.client.get(f"/agent/runs/{run['run_id']}", headers=self.headers).status_code,
            200,
        )
        with SessionLocal() as db:
            self.assertEqual(db.query(AgentRun).filter_by(run_id=run["run_id"]).one().status, "COMPLETED")
            phases = [checkpoint.phase for checkpoint in db.query(AgentRunCheckpoint).order_by(AgentRunCheckpoint.sequence).all()]
            self.assertEqual(phases, ["RUNNING", "COMPLETED"])


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
        with patch.object(settings, 'google_forms_source_id', 'summary-integration'), patch.object(settings, 'google_forms_agent_numeric_fields', 'test,temp'):
            summary = get_form_summary()
            self.assertEqual(summary['response_count'], 2)
            self.assertEqual(summary['numeric_fields']['test']['mean'], 2)
            self.assertNotIn('Email', str(summary))
            self.assertEqual(get_form_summary(workspace_id=other_id)['response_count'], 0)
            self.assertEqual(run_agent(goal='test', context='', constraints={})['form_summary'], summary)


if __name__ == "__main__":
    unittest.main()
