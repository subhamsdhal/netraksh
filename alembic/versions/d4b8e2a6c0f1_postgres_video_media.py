"""Store the two small camera sources and their control records in PostgreSQL.

Revision ID: d4b8e2a6c0f1
Revises: c9e2a4f6b8d0
"""
from alembic import op
import sqlalchemy as sa


revision = "d4b8e2a6c0f1"
down_revision = "c9e2a4f6b8d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_media_objects",
        sa.Column("object_key", sa.String(320), primary_key=True),
        sa.Column("camera_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("source_generation", sa.Integer(), nullable=True),
        sa.Column("prepared_source_key", sa.String(320), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 49000000", name="ck_video_media_size"),
    )
    op.create_index("ix_video_media_camera_session", "video_media_objects", ["camera_id", "session_id"])
    op.create_table(
        "video_control_records",
        sa.Column("object_key", sa.String(320), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("video_control_records")
    op.drop_index("ix_video_media_camera_session", table_name="video_media_objects")
    op.drop_table("video_media_objects")
