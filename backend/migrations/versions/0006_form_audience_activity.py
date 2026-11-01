"""Add audience and activity labels; preserve historical dates for compatibility."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("school", "department_grade", "activity_name"):
        op.add_column("form_responses", sa.Column(name, sa.String(255), nullable=True))
    op.execute("COMMENT ON COLUMN form_responses.event_date IS 'Legacy activity date; no longer populated or read by current form workflow'")


def downgrade():
    raise RuntimeError("Forward-only migration; restore a reviewed backup instead.")
