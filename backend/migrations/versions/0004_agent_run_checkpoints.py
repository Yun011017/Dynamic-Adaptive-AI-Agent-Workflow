"""Add worker retries and durable Agent-run checkpoints."""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("agent_runs", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "agent_run_checkpoints",
        sa.Column("agent_run_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("state_payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_agent_run_checkpoints_sequence"),
        sa.ForeignKeyConstraint(["workspace_id", "agent_run_id"], ["agent_runs.workspace_id", "agent_runs.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "agent_run_id", "sequence"),
    )
    op.create_index("ix_agent_run_checkpoints_workspace_id", "agent_run_checkpoints", ["workspace_id"])


def downgrade():
    raise RuntimeError("Forward-only migration; restore a reviewed backup instead.")
