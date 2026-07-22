"""Add is_pilot flag to users table

Revision ID: 006_add_is_pilot_flag
Revises: 005_pilot_profile_fields
Create Date: 2026-02-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_add_is_pilot_flag'
down_revision = '005_pilot_profile_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_pilot', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('users', 'is_pilot', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'is_pilot')
