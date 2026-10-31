"""Add structured form answers without changing existing raw events."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_responses",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("external_event_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("is_member", sa.Boolean(), nullable=True),
        sa.Column("will_attend", sa.Boolean(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalization_errors", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "external_event_id"], ["external_events.workspace_id", "external_events.id"]),
        sa.UniqueConstraint("workspace_id", "external_event_id", name="uq_form_response_event"),
    )
    op.create_index("ix_form_responses_workspace_id", "form_responses", ["workspace_id"])


def downgrade():
    raise RuntimeError("Forward-only migration; restore a reviewed backup instead.")
