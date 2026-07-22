"""Add tip metadata to errands

Revision ID: 011_add_tip_metadata
Revises: 010_add_promo_codes
Create Date: 2026-04-01

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "011_add_tip_metadata"
down_revision = "010_add_promo_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "errands",
        sa.Column("tip_amount_total_minor", sa.Integer(), nullable=True),
    )
    op.add_column(
        "errands",
        sa.Column("tip_currency", sa.String(), nullable=True),
    )
    op.add_column(
        "errands",
        sa.Column("tip_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "errands",
        sa.Column("tip_stripe_session_id", sa.String(), nullable=True),
    )

    op.create_index(
        "ix_errands_tip_paid_at",
        "errands",
        ["tip_paid_at"],
        unique=False,
    )
    op.create_index(
        "ix_errands_tip_stripe_session_id",
        "errands",
        ["tip_stripe_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_errands_tip_stripe_session_id", table_name="errands")
    op.drop_index("ix_errands_tip_paid_at", table_name="errands")

    op.drop_column("errands", "tip_stripe_session_id")
    op.drop_column("errands", "tip_paid_at")
    op.drop_column("errands", "tip_currency")
    op.drop_column("errands", "tip_amount_total_minor")
