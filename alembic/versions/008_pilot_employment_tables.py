"""Add pilot employment application tables

Revision ID: 008_pilot_employment_tables
Revises: 007_backfill_is_pilot
Create Date: 2026-03-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_pilot_employment_tables'
down_revision = '007_backfill_is_pilot'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pilot_employment_applications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('first_name', sa.String(), nullable=False),
        sa.Column('last_name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('experience', sa.Text(), nullable=True),
        sa.Column('availability', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='submitted'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index(
        'ix_pilot_employment_applications_email',
        'pilot_employment_applications',
        ['email'],
    )

    op.create_table(
        'pilot_employment_attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('pilot_employment_applications.id'), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('stored_filename', sa.String(), nullable=False, unique=True),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index(
        'ix_pilot_employment_attachments_application_id',
        'pilot_employment_attachments',
        ['application_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_pilot_employment_attachments_application_id', table_name='pilot_employment_attachments')
    op.drop_table('pilot_employment_attachments')
    op.drop_index('ix_pilot_employment_applications_email', table_name='pilot_employment_applications')
    op.drop_table('pilot_employment_applications')
