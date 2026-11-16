"""Track temporary and referenced R2 media assets."""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("public_url", sa.String(length=1024), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("referenced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("media_type IN ('image','video')", name="ck_media_assets_type"),
        sa.CheckConstraint("status IN ('PENDING','READY','REFERENCED','FAILED','DELETED')", name="ck_media_assets_status"),
        sa.CheckConstraint("size_bytes > 0", name="ck_media_assets_size"),
        sa.UniqueConstraint("workspace_id", "object_key", name="uq_media_assets_object_key"),
        sa.UniqueConstraint("workspace_id", "public_url", name="uq_media_assets_public_url"),
    )
    op.create_index("ix_media_assets_workspace_id", "media_assets", ["workspace_id"])
    op.create_index("ix_media_assets_expires_at", "media_assets", ["expires_at"])


def downgrade():
    op.drop_index("ix_media_assets_expires_at", table_name="media_assets")
    op.drop_index("ix_media_assets_workspace_id", table_name="media_assets")
    op.drop_table("media_assets")
