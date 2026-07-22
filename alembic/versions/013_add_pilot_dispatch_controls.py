"""add pilot dispatch controls

Revision ID: 013_add_pilot_dispatch_controls
Revises: 012_add_errand_messages
Create Date: 2026-04-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "013_add_pilot_dispatch_controls"
down_revision = "012_add_errand_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "pilot_availability",
            sa.String(),
            nullable=False,
            server_default="offline",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "admin_dispatch_status",
            sa.String(),
            nullable=False,
            server_default="enabled",
        ),
    )
    op.add_column(
        "users",
        sa.Column("admin_dispatch_note", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("pilot_status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("pilot_status_changed_by", sa.Integer(), nullable=True),
    )

    op.execute(
        "UPDATE users SET pilot_availability = 'offline' WHERE pilot_availability IS NULL"
    )
    op.execute(
        "UPDATE users SET admin_dispatch_status = 'enabled' WHERE admin_dispatch_status IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "pilot_status_changed_by")
    op.drop_column("users", "pilot_status_changed_at")
    op.drop_column("users", "admin_dispatch_note")
    op.drop_column("users", "admin_dispatch_status")
    op.drop_column("users", "pilot_availability")
