"""Add source metadata to pilot locations

Revision ID: 017_tracking_location_source
Revises: 016_service_setup_errands
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "017_tracking_location_source"
down_revision = "016_service_setup_errands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pilot_locations",
        sa.Column("source", sa.String(), nullable=False, server_default="mobile_app"),
    )
    op.add_column(
        "pilot_locations",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE pilot_locations SET source = 'mobile_app' WHERE source IS NULL")
    op.execute("UPDATE pilot_locations SET recorded_at = created_at WHERE recorded_at IS NULL")


def downgrade() -> None:
    op.drop_column("pilot_locations", "recorded_at")
    op.drop_column("pilot_locations", "source")