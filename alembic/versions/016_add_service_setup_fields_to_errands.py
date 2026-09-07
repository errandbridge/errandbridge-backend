"""Add service setup pricing fields to errands

Revision ID: 016_service_setup_errands
Revises: 015_add_subscriptions_and_checkout_sessions
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = "016_service_setup_errands"
down_revision = "015_add_subscriptions_checkout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("errands", sa.Column("category_id", sa.String(), nullable=True))
    op.add_column("errands", sa.Column("support_type", sa.String(), nullable=True))
    op.add_column("errands", sa.Column("preferred_time", sa.String(), nullable=True))
    op.add_column("errands", sa.Column("priority_level", sa.String(), nullable=True))
    op.add_column("errands", sa.Column("distance_km", sa.Float(), nullable=True))
    op.add_column(
        "errands", sa.Column("final_price_minor", sa.Integer(), nullable=True)
    )
    op.add_column(
        "errands", sa.Column("final_price_currency", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("errands", "final_price_currency")
    op.drop_column("errands", "final_price_minor")
    op.drop_column("errands", "distance_km")
    op.drop_column("errands", "priority_level")
    op.drop_column("errands", "preferred_time")
    op.drop_column("errands", "support_type")
    op.drop_column("errands", "category_id")
