"""Add payment metadata to errands

Revision ID: 009_add_payment_metadata
Revises: 008_pilot_employment_tables
Create Date: 2026-03-27

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "009_add_payment_metadata"
down_revision = "008_pilot_employment_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "errands",
        sa.Column("payment_amount_total_minor", sa.Integer(), nullable=True),
    )
    op.add_column(
        "errands",
        sa.Column("payment_currency", sa.String(), nullable=True),
    )
    op.add_column(
        "errands",
        sa.Column("payment_amount_ngn_major", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("errands", "payment_amount_ngn_major")
    op.drop_column("errands", "payment_currency")
    op.drop_column("errands", "payment_amount_total_minor")
