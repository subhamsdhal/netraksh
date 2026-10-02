"""Persist exact per-run telemetry summaries.

Revision ID: b7d9f1a3c5e7
Revises: a6c8e0f2b4d6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d9f1a3c5e7"
down_revision: Union[str, Sequence[str], None] = "a6c8e0f2b4d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_run_summaries",
        sa.Column("analysis_session_id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), nullable=False),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("analysis_generation", sa.Integer(), nullable=False),
        sa.Column("first_telemetry_at", sa.Float(), nullable=False),
        sa.Column("last_telemetry_at", sa.Float(), nullable=False),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.Column("final_frame_index", sa.Integer(), nullable=True),
        sa.Column("final_video_time", sa.Float(), nullable=True),
        sa.Column("processing_fps", sa.Float(), nullable=True),
        sa.Column("source_fps", sa.Float(), nullable=True),
        sa.Column("frame_width", sa.Integer(), nullable=True),
        sa.Column("frame_height", sa.Integer(), nullable=True),
        sa.Column("person_count", sa.Integer(), nullable=True),
        sa.Column("vehicle_count", sa.Integer(), nullable=True),
        sa.Column("track_count", sa.Integer(), nullable=True),
        sa.Column("scene_condition", sa.String(64), nullable=True),
        sa.Column("lighting_state", sa.String(64), nullable=True),
        sa.Column("detection_method", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_analysis_run_summary_camera_stream",
        "analysis_run_summaries",
        ["camera_id", "stream_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_run_summary_camera_stream", table_name="analysis_run_summaries")
    op.drop_table("analysis_run_summaries")
