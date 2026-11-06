"""Add approval_requests table for human review workflow."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING_REVIEW", nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=255), server_default="admin", nullable=False),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "action_id"],
            ["execution_actions.workspace_id", "execution_actions.id"],
            name="fk_approval_action_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'EXPIRED')",
            name="ck_approval_status",
        ),
    )
    op.create_index("ix_approval_requests_workspace_id", "approval_requests", ["workspace_id"])
    op.create_index("ix_approval_requests_action_id", "approval_requests", ["action_id"])

def downgrade():
    raise RuntimeError("Forward-only migration; restore a backup instead of dropping tables.")