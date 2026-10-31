"""Run from backend: python -m scripts.manage migrate|seed|check|baseline-legacy."""
import sys
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool
from app.config import settings

ROOT = Path(__file__).resolve().parents[1]


def run(action):
    config = Config(str(ROOT / "alembic.ini"))
    url = settings.migration_database_url or settings.database_url
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 10})
    if action == "migrate":
        command.upgrade(config, "head")
        print("Migration applied")
    elif action == "baseline-legacy":
        with engine.connect() as c:
            inspector = inspect(c)
            expected = {"goals": {"id","title","description","status","created_at"}, "strategies": {"id","goal_id","version","content","rationale","created_at"}, "executions": {"id","strategy_id","status","result_summary","created_at"}}
            if set(inspector.get_table_names()) != set(expected):
                raise RuntimeError("Baseline refused: database is not the exact legacy prototype")
            for table, columns in expected.items():
                if {v["name"] for v in inspector.get_columns(table)} != columns:
                    raise RuntimeError("Baseline refused: unexpected columns")
        command.stamp(config, "0001")
        print("Legacy baseline recorded; now run migrate")
    elif action == "seed":
        with engine.begin() as c:
            c.connection.driver_connection.execute((ROOT / "seed.sql").read_text(encoding="utf-8"), prepare=False)
        print("Synthetic seed committed (idempotent)")
    elif action == "check":
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
            revision = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            tables = set(inspect(c).get_table_names())
            expected = {"workspaces","members","goals","strategies","executions","execution_actions","observations","external_events","agent_runs","agent_run_checkpoints","form_responses"}
            expected_revision = ScriptDirectory.from_config(config).get_current_head()
            if not expected <= tables or revision != expected_revision:
                raise RuntimeError("Schema not up to date")
            count = c.execute(text("SELECT count(*) FROM goals g JOIN workspaces w ON w.id=g.workspace_id JOIN strategies s ON s.goal_id=g.id AND s.workspace_id=g.workspace_id JOIN executions e ON e.strategy_id=s.id AND e.workspace_id=s.workspace_id WHERE w.slug='development' AND g.title='[seed] Club campaign' AND s.version=1")).scalar_one()
            print(f"Database connected; migration={revision}; core tables={len(expected)}; seed chains={count}")
    else:
        raise ValueError("Use migrate, seed, check or baseline-legacy")
    engine.dispose()


if __name__ == "__main__":
    try:
        run(sys.argv[1])
    except Exception as exc:
        # Never print DB URL, driver message, SQL parameters or connection secrets.
        print(f"Operation failed ({type(exc).__name__}); verify credentials, network and migration state.", file=sys.stderr)
        sys.exit(1)
