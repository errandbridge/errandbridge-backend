"""Add stripe_customer_id to users table

Revision ID: 023_add_stripe_customer_id_to_users
Revises: 022_property_inspection
Create Date: 2026-09-24

This migration adds the stripe_customer_id column to the users table,
which is defined in the User model but was missing from all prior migrations.
Uses IF NOT EXISTS guards to be idempotent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_add_stripe_customer_id_to_users"
down_revision: Union[str, Sequence[str], None] = "022_property_inspection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add stripe_customer_id to users table if it doesn't already exist.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'stripe_customer_id'
            ) THEN
                ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR;
            END IF;
        END $$;
    """)

    # Create index if it doesn't already exist.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'users'
                  AND indexname = 'ix_users_stripe_customer_id'
            ) THEN
                CREATE INDEX ix_users_stripe_customer_id ON users (stripe_customer_id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'users'
                  AND indexname = 'ix_users_stripe_customer_id'
            ) THEN
                DROP INDEX ix_users_stripe_customer_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'stripe_customer_id'
            ) THEN
                ALTER TABLE users DROP COLUMN stripe_customer_id;
            END IF;
        END $$;
    """)
