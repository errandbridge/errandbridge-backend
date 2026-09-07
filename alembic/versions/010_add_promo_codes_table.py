"""Add promo codes table

Revision ID: 010_add_promo_codes
Revises: 009_add_payment_metadata
Create Date: 2026-04-01

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "010_add_promo_codes"
down_revision = "009_add_payment_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("redeemed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "redeemed_errand_id",
            sa.Integer(),
            sa.ForeignKey("errands.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )

    op.create_index("ix_promo_codes_code", "promo_codes", ["code"], unique=True)
    op.create_index("ix_promo_codes_user_id", "promo_codes", ["user_id"], unique=False)
    op.create_index(
        "ix_promo_codes_created_by_admin_id",
        "promo_codes",
        ["created_by_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_promo_codes_redeemed_errand_id",
        "promo_codes",
        ["redeemed_errand_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_promo_codes_redeemed_errand_id", table_name="promo_codes")
    op.drop_index("ix_promo_codes_created_by_admin_id", table_name="promo_codes")
    op.drop_index("ix_promo_codes_user_id", table_name="promo_codes")
    op.drop_index("ix_promo_codes_code", table_name="promo_codes")
    op.drop_table("promo_codes")
