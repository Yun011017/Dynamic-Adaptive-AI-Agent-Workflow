"""Associate new Agent runs with an existing workspace Goal."""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable keeps historical AgentRun rows readable; the API requires it for new runs.
    op.add_column("agent_runs", sa.Column("goal_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_agent_run_goal_tenant",
        "agent_runs",
        "goals",
        ["workspace_id", "goal_id"],
        ["workspace_id", "id"],
    )
    op.create_index("ix_agent_runs_goal_id", "agent_runs", ["goal_id"])


def downgrade():
    op.drop_index("ix_agent_runs_goal_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_run_goal_tenant", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "goal_id")
