"""Persist concrete analysis run identity on events."""
from alembic import op
import sqlalchemy as sa


revision = "c2b4d6e8f0a2"
down_revision = "b1a3e5c7d9f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("analysis_session_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_events_analysis_session_id",
        "events",
        ["analysis_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_analysis_session_id", table_name="events")
    op.drop_column("events", "analysis_session_id")
