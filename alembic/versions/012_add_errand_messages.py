"""Add errand messages

Revision ID: 012_add_errand_messages
Revises: 011_add_tip_metadata
Create Date: 2026-04-01

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "012_add_errand_messages"
down_revision = "011_add_tip_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "errand_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("errand_id", sa.Integer(), sa.ForeignKey("errands.id"), nullable=False),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "message",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_errand_messages_errand_id",
        "errand_messages",
        ["errand_id"],
        unique=False,
    )
    op.create_index(
        "ix_errand_messages_sender_id",
        "errand_messages",
        ["sender_id"],
        unique=False,
    )
    op.create_index(
        "ix_errand_messages_created_at",
        "errand_messages",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_errand_messages_created_at", table_name="errand_messages")
    op.drop_index("ix_errand_messages_sender_id", table_name="errand_messages")
    op.drop_index("ix_errand_messages_errand_id", table_name="errand_messages")
    op.drop_table("errand_messages")
