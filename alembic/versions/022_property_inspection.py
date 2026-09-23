"""add property inspection

Revision ID: 022_property_inspection
Revises: 021_pilot_status_by_uuid
Create Date: 2026-09-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "022_property_inspection"
down_revision: Union[str, Sequence[str], None] = "021_pilot_status_by_uuid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('errands', sa.Column('inspection_location', sa.String(), nullable=True))
    
    op.create_table(
        'errand_inspection_items',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('errand_id', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('requires_photo', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('completed', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('photo_url', sa.String(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.String(), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_errand_inspection_items_errand_id'), 'errand_inspection_items', ['errand_id'], unique=False)
    op.create_index(op.f('ix_errand_inspection_items_id'), 'errand_inspection_items', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_errand_inspection_items_id'), table_name='errand_inspection_items')
    op.drop_index(op.f('ix_errand_inspection_items_errand_id'), table_name='errand_inspection_items')
    op.drop_table('errand_inspection_items')
    op.drop_column('errands', 'inspection_location')
