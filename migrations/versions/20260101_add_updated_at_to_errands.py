"""
Alembic migration to add updated_at column to errands table
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column(
        'errands',
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now())
    )

def downgrade():
    op.drop_column('errands', 'updated_at')
