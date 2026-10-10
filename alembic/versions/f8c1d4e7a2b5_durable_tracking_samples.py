"""Persist individual analyzed-HUD samples across backend restarts.

Revision ID: f8c1d4e7a2b5
Revises: e7a9c1d3f5b2
"""
from alembic import op
import sqlalchemy as sa


revision = "f8c1d4e7a2b5"
down_revision = "e7a9c1d3f5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_tracking_samples",
        sa.Column("analysis_session_id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("frame_index", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.String(36), nullable=False),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("analysis_generation", sa.Integer(), nullable=False),
        sa.Column("video_time", sa.Float(), nullable=True),
        sa.Column("sample_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_analysis_tracking_sample_run_time",
        "analysis_tracking_samples",
        ["analysis_session_id", "video_time", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_tracking_sample_run_time",
        table_name="analysis_tracking_samples",
    )
    op.drop_table("analysis_tracking_samples")
