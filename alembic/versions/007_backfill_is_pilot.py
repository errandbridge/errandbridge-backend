"""Backfill is_pilot for existing pilot users

Revision ID: 007_backfill_is_pilot
Revises: 006_add_is_pilot_flag
Create Date: 2026-02-16 00:00:01.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '007_backfill_is_pilot'
down_revision = '006_add_is_pilot_flag'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET is_pilot = TRUE
        WHERE is_pilot IS FALSE
          AND (
            EXISTS (SELECT 1 FROM pilot_locations pl WHERE pl.pilot_id = users.id)
            OR EXISTS (SELECT 1 FROM errands e WHERE e.pilot_id = users.id)
          )
        """
    )


def downgrade() -> None:
    # Data backfill only; no downgrade reversal to avoid data loss.
    pass