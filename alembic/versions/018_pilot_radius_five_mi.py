"""set pilot dispatch default radius to five miles

Revision ID: 018_pilot_radius_five_mi
Revises: 017_tracking_location_source
Create Date: 2026-07-07 13:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "018_pilot_radius_five_mi"
down_revision = "017_tracking_location_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.alter_column(
		"pilot_dispatch_policies",
		"open_pool_radius_miles",
		existing_type=sa.Integer(),
		server_default="5",
	)
	op.execute(
		"UPDATE pilot_dispatch_policies SET open_pool_radius_miles = 5 WHERE id = 1"
	)


def downgrade() -> None:
	op.execute(
		"UPDATE pilot_dispatch_policies SET open_pool_radius_miles = 10 WHERE id = 1 AND open_pool_radius_miles = 5"
	)
	op.alter_column(
		"pilot_dispatch_policies",
		"open_pool_radius_miles",
		existing_type=sa.Integer(),
		server_default="10",
	)