"""Persist structured ANPR observations on events."""
from alembic import op
import sqlalchemy as sa

revision = "7f1b9a2c4d11"
down_revision = "3d86d25c0fdc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column in (
        ("raw_plate_text", sa.String(64)),
        ("normalized_plate_text", sa.String(32)),
        ("localization_confidence", sa.Float()),
        ("ocr_confidence", sa.Float()),
        ("observations_count", sa.Integer()),
        ("processing_method", sa.String(128)),
        ("fusion_state", sa.String(32)),
        ("validation_status", sa.String(24)),
        ("watchlist_match", sa.Boolean()),
    ):
        op.add_column("events", sa.Column(name, column, nullable=True))
    op.create_index("ix_events_normalized_plate_text", "events", ["normalized_plate_text"])


def downgrade() -> None:
    op.drop_index("ix_events_normalized_plate_text", table_name="events")
    for name in ("watchlist_match", "validation_status", "fusion_state", "processing_method", "observations_count", "ocr_confidence", "localization_confidence", "normalized_plate_text", "raw_plate_text"):
        op.drop_column("events", name)
