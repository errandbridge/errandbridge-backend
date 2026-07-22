"""
Revision to add note field to errands table
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('errands', sa.Column('note', sa.String(), nullable=True))

def downgrade():
    op.drop_column('errands', 'note')
