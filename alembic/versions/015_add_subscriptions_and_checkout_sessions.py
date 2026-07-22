"""Add subscriptions and Stripe checkout sessions

Revision ID: 015_add_subscriptions_checkout
Revises: 014_add_pilot_dispatch_policy
Create Date: 2026-04-16

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "015_add_subscriptions_checkout"
down_revision = "014_add_pilot_dispatch_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="stripe"),
        sa.Column("plan", sa.String(), nullable=False, server_default="plus"),
        sa.Column("status", sa.String(), nullable=False, server_default="none"),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_client_subscriptions_id"), "client_subscriptions", ["id"], unique=False)
    op.create_index("ix_client_subscriptions_user_id", "client_subscriptions", ["user_id"], unique=False)
    op.create_index(
        "ix_client_subscriptions_stripe_customer_id",
        "client_subscriptions",
        ["stripe_customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_client_subscriptions_stripe_subscription_id",
        "client_subscriptions",
        ["stripe_subscription_id"],
        unique=True,
    )

    op.create_table(
        "stripe_checkout_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stripe_session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False, server_default="payment"),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("amount_total_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("used_for_errand_id", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_session_id", name="uq_stripe_checkout_sessions_stripe_session_id"),
    )
    op.create_index(
        op.f("ix_stripe_checkout_sessions_id"),
        "stripe_checkout_sessions",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_stripe_checkout_sessions_stripe_session_id",
        "stripe_checkout_sessions",
        ["stripe_session_id"],
        unique=True,
    )
    op.create_index(
        "ix_stripe_checkout_sessions_user_id",
        "stripe_checkout_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_stripe_checkout_sessions_stripe_customer_id",
        "stripe_checkout_sessions",
        ["stripe_customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_stripe_checkout_sessions_stripe_subscription_id",
        "stripe_checkout_sessions",
        ["stripe_subscription_id"],
        unique=False,
    )
    op.create_index(
        "ix_stripe_checkout_sessions_used_for_errand_id",
        "stripe_checkout_sessions",
        ["used_for_errand_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_checkout_sessions_used_for_errand_id", table_name="stripe_checkout_sessions")
    op.drop_index("ix_stripe_checkout_sessions_stripe_subscription_id", table_name="stripe_checkout_sessions")
    op.drop_index("ix_stripe_checkout_sessions_stripe_customer_id", table_name="stripe_checkout_sessions")
    op.drop_index("ix_stripe_checkout_sessions_user_id", table_name="stripe_checkout_sessions")
    op.drop_index("ix_stripe_checkout_sessions_stripe_session_id", table_name="stripe_checkout_sessions")
    op.drop_index(op.f("ix_stripe_checkout_sessions_id"), table_name="stripe_checkout_sessions")
    op.drop_table("stripe_checkout_sessions")

    op.drop_index("ix_client_subscriptions_stripe_subscription_id", table_name="client_subscriptions")
    op.drop_index("ix_client_subscriptions_stripe_customer_id", table_name="client_subscriptions")
    op.drop_index("ix_client_subscriptions_user_id", table_name="client_subscriptions")
    op.drop_index(op.f("ix_client_subscriptions_id"), table_name="client_subscriptions")
    op.drop_table("client_subscriptions")
