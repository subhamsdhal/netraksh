"""Scope replay evidence chains to signed analysis sessions.

This is additive only.  Existing evidence rows retain their null scope and
therefore their historical verification state.
"""
from alembic import op
import sqlalchemy as sa


revision = "b1a3e5c7d9f1"
down_revision = "9d4e6b2f1a88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evidence_chain",
        sa.Column("analysis_session_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_evidence_chain_edge_analysis_seq",
        "evidence_chain",
        ["edge_device_id", "analysis_session_id", "sequence_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_chain_edge_analysis_seq", table_name="evidence_chain")
    op.drop_column("evidence_chain", "analysis_session_id")
