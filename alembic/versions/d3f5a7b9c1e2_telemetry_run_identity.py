"""Persist real analysis-run identity on latest telemetry snapshots."""
from alembic import op
import sqlalchemy as sa


revision = "d3f5a7b9c1e2"
down_revision = "c2b4d6e8f0a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_telemetry", sa.Column("analysis_session_id", sa.String(length=36), nullable=True))
    op.add_column("analysis_telemetry", sa.Column("analysis_generation", sa.Integer(), nullable=True))
    op.add_column("analysis_telemetry", sa.Column("frame_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_telemetry", "frame_index")
    op.drop_column("analysis_telemetry", "analysis_generation")
    op.drop_column("analysis_telemetry", "analysis_session_id")
