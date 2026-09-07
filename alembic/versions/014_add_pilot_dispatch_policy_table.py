"""add pilot dispatch policy table

Revision ID: 014_add_pilot_dispatch_policy
Revises: 013_add_pilot_dispatch_controls
Create Date: 2026-04-12 19:15:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "014_add_pilot_dispatch_policy"
down_revision = "013_add_pilot_dispatch_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pilot_dispatch_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "show_all_jobs_to_pilots",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "open_pool_radius_miles",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pilot_dispatch_policies_id"),
        "pilot_dispatch_policies",
        ["id"],
        unique=False,
    )
    op.execute(
        "INSERT INTO pilot_dispatch_policies (id, show_all_jobs_to_pilots, open_pool_radius_miles) VALUES (1, false, 10)"
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pilot_dispatch_policies_id"), table_name="pilot_dispatch_policies"
    )
    op.drop_table("pilot_dispatch_policies")
