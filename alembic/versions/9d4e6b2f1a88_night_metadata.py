"""Persist measured low-light and motion-fallback metadata."""
from alembic import op
import sqlalchemy as sa

revision = "9d4e6b2f1a88"
down_revision = "8c2f4a1b9d77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column in (
        ("lighting_state", sa.String(32)),
        ("mean_luminance", sa.Float()),
        ("dark_pixel_ratio", sa.Float()),
        ("enhancement_applied", sa.Boolean()),
        ("detection_method", sa.String(32)),
        ("motion_area", sa.Float()),
        ("motion_persistence", sa.Integer()),
    ):
        op.add_column("events", sa.Column(name, column, nullable=True))


def downgrade() -> None:
    for name in ("motion_persistence", "motion_area", "detection_method", "enhancement_applied", "dark_pixel_ratio", "mean_luminance", "lighting_state"):
        op.drop_column("events", name)
