"""add stable public UUID to users

Revision ID: 019_add_user_uuid
Revises: 018_pilot_radius_five_mi
Create Date: 2026-07-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "019_add_user_uuid"
down_revision = "018_pilot_radius_five_mi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("user_uuid", sa.String(length=36), nullable=True))

    # Backfill existing rows with deterministic UUID-formatted values derived from
    # stable existing fields. This avoids depending on DB extensions such as
    # pgcrypto/uuid-ossp during deployment while still producing unique identifiers
    # for current rows.
    op.execute(
        """
        UPDATE users
        SET user_uuid = lower(
            substr(md5(id::text || ':' || coalesce(email, '') || ':' || coalesce(created_at::text, '')), 1, 8) || '-' ||
            substr(md5(id::text || ':' || coalesce(email, '') || ':' || coalesce(created_at::text, '')), 9, 4) || '-' ||
            substr(md5(id::text || ':' || coalesce(email, '') || ':' || coalesce(created_at::text, '')), 13, 4) || '-' ||
            substr(md5(id::text || ':' || coalesce(email, '') || ':' || coalesce(created_at::text, '')), 17, 4) || '-' ||
            substr(md5(id::text || ':' || coalesce(email, '') || ':' || coalesce(created_at::text, '')), 21, 12)
        )
        WHERE user_uuid IS NULL
        """
    )

    op.alter_column("users", "user_uuid", existing_type=sa.String(length=36), nullable=False)
    op.create_index("ix_users_user_uuid", "users", ["user_uuid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_user_uuid", table_name="users")
    op.drop_column("users", "user_uuid")
