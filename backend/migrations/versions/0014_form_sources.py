"""Register multiple activity-specific form endpoints."""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("apps_script_url", sa.String(2048), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("workspace_id", "source_id", name="uq_form_sources_identity"),
        sa.UniqueConstraint("workspace_id", "apps_script_url", name="uq_form_sources_endpoint"),
        sa.ForeignKeyConstraint(["workspace_id", "goal_id"], ["goals.workspace_id", "goals.id"], name="fk_form_source_goal"),
    )
    op.create_index("ix_form_sources_workspace_id", "form_sources", ["workspace_id"])


def downgrade():
    raise RuntimeError("Forward-only migration; restore a reviewed backup instead.")
