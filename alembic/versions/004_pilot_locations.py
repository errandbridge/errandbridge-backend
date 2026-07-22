"""Add pilot locations table for GPS tracking

Revision ID: 004_pilot_locations
Revises: 98d01594b2a6
Create Date: 2026-01-07 05:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004_pilot_locations'
down_revision = '98d01594b2a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create pilot_locations table
    op.create_table(
        'pilot_locations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('errand_id', sa.Integer(), nullable=False),
        sa.Column('pilot_id', sa.Integer(), nullable=False),
        sa.Column('latitude', sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column('longitude', sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('speed', sa.Float(), nullable=True),
        sa.Column('heading', sa.Float(), nullable=True),
        sa.Column('altitude', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['errand_id'], ['errands.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pilot_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_pilot_locations_errand_id', 'pilot_locations', ['errand_id'])
    op.create_index('idx_pilot_locations_pilot_id', 'pilot_locations', ['pilot_id'])
    op.create_index('idx_pilot_locations_created_at', 'pilot_locations', ['created_at'], postgresql_using='DESC')
    op.create_index('idx_pilot_locations_errand_created', 'pilot_locations', ['errand_id', 'created_at'], postgresql_using='DESC')


def downgrade() -> None:
    op.drop_index('idx_pilot_locations_errand_created', table_name='pilot_locations')
    op.drop_index('idx_pilot_locations_created_at', table_name='pilot_locations')
    op.drop_index('idx_pilot_locations_pilot_id', table_name='pilot_locations')
    op.drop_index('idx_pilot_locations_errand_id', table_name='pilot_locations')
    op.drop_table('pilot_locations')
