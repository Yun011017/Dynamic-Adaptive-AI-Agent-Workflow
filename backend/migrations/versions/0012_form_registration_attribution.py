"""Store official registration fields and tenant-scoped execution attribution."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    for name, length in (("email", 255), ("respondent_name", 255), ("copy_source", 16)):
        op.add_column("form_responses", sa.Column(name, sa.String(length), nullable=True))
    op.add_column("form_responses", sa.Column("execution_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_form_response_execution", "form_responses", "executions",
                          ["workspace_id", "execution_id"], ["workspace_id", "id"])
    op.create_index("ix_form_responses_execution", "form_responses", ["workspace_id", "execution_id"])


def downgrade():
    raise RuntimeError("Forward-only migration; restore a reviewed backup instead.")
