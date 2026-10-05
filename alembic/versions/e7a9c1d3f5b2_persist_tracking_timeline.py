"""Persist deliberate upload lineage and completed analyzed HUD timelines."""
from alembic import op
import sqlalchemy as sa


revision = "e7a9c1d3f5b2"
down_revision = "b7d9f1a3c5e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_telemetry", sa.Column("source_generation", sa.Integer(), nullable=True))
    op.add_column("analysis_run_summaries", sa.Column("source_generation", sa.Integer(), nullable=True))
    op.add_column("analysis_run_summaries", sa.Column("detector_fps", sa.Float(), nullable=True))
    op.add_column("analysis_run_summaries", sa.Column("hud_fps", sa.Float(), nullable=True))
    op.add_column(
        "analysis_run_summaries",
        sa.Column("tracking_sample_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "analysis_run_summaries",
        sa.Column("tracking_timeline_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("analysis_run_summaries", "tracking_timeline_json")
    op.drop_column("analysis_run_summaries", "tracking_sample_count")
    op.drop_column("analysis_run_summaries", "hud_fps")
    op.drop_column("analysis_run_summaries", "detector_fps")
    op.drop_column("analysis_run_summaries", "source_generation")
    op.drop_column("analysis_telemetry", "source_generation")
