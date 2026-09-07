"""
Alembic migration for errand_events table
"""

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "errand_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "errand_id",
            sa.Integer(),
            sa.ForeignKey("errands.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("old_status", sa.String(), nullable=True),
        sa.Column("new_status", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_table("errand_events")
