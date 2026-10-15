"""Baseline matching the original three-table prototype."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("goals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("status", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("strategies", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("goal_id", sa.Integer(), sa.ForeignKey("goals.id"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("rationale", sa.Text()), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("executions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("strategy_id", sa.Integer(), sa.ForeignKey("strategies.id"), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("result_summary", sa.Text()), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))


def downgrade():
    op.drop_table("executions")
    op.drop_table("strategies")
    op.drop_table("goals")
