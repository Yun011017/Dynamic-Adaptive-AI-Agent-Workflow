"""Allow platform content drafts to be scheduled and superseded by a newer version."""

from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_actions_status", "execution_actions", type_="check")
    op.create_check_constraint(
        "ck_actions_status",
        "execution_actions",
        "status IN ('DRAFT','SCHEDULED','PENDING_REVIEW','APPROVED','REJECTED','EXPIRED','EXECUTING','SUCCEEDED','FAILED','TIMEOUT','VERIFYING','MANUAL_REVIEW','SUPERSEDED')",
    )


def downgrade():
    raise RuntimeError("Forward-only data-preserving migration; restore a reviewed backup instead of removing content draft states.")
