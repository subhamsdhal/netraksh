"""Persist explicit face watchlist evaluation metadata."""
from alembic import op
import sqlalchemy as sa

revision = "8c2f4a1b9d77"
down_revision = "7f1b9a2c4d11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("face_match_status", sa.String(32)),
        ("watchlist_person_id", sa.String(36)),
        ("watchlist_label", sa.String(128)),
        ("recognition_score", sa.Float()),
        ("recognition_threshold", sa.Float()),
        ("recognition_engine", sa.String(32)),
        ("face_quality_status", sa.String(32)),
        ("recognition_observation_count", sa.Integer()),
        ("face_bbox_json", sa.Text()),
        ("face_engine", sa.String(32)),
        ("similarity_score", sa.Float()),
        ("recognition_state", sa.String(32)),
        ("alignment_method", sa.String(32)),
    )
    for name, column in columns:
        op.add_column("events", sa.Column(name, column, nullable=True))


def downgrade() -> None:
    for name in (
        "alignment_method", "recognition_state", "similarity_score", "face_engine",
        "face_bbox_json", "recognition_observation_count", "face_quality_status",
        "recognition_engine", "recognition_threshold", "recognition_score",
        "watchlist_label", "watchlist_person_id", "face_match_status",
    ):
        op.drop_column("events", name)
