"""Store the latest KPI evaluation snapshot for an execution."""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("executions", sa.Column("evaluation_result", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("executions", "evaluation_result")
