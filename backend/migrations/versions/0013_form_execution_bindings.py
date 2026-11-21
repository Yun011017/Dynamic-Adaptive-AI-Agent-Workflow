"""Persist form source to execution bindings."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_execution_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("copy_source", sa.String(16), nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("workspace_id", "source_id", "copy_source", name="uq_form_execution_binding_source"),
        sa.ForeignKeyConstraint(["workspace_id", "execution_id"], ["executions.workspace_id", "executions.id"], name="fk_form_binding_execution"),
        sa.CheckConstraint("copy_source IN ('人工','ai')", name="ck_form_binding_copy_source"),
    )
    op.create_index("ix_form_execution_bindings_workspace_id", "form_execution_bindings", ["workspace_id"])


def downgrade():
    raise RuntimeError("Forward-only migration; restore a reviewed backup instead.")
