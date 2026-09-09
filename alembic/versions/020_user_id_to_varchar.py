"""alter user_id columns to varchar

Revision ID: 020_user_id_to_varchar
Revises: 829d03791d91
Create Date: 2026-09-09 02:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '020_user_id_to_varchar'
down_revision: Union[str, Sequence[str], None] = '829d03791d91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. errand_events.user_id: integer -> varchar
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'errand_events' 
                AND column_name = 'user_id' 
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE errand_events ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;
            END IF;
        END $$;
    """)

    # 2. client_subscriptions.user_id: integer -> varchar
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'client_subscriptions' 
                AND column_name = 'user_id' 
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE client_subscriptions ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;
            END IF;
        END $$;
    """)

    # 3. stripe_checkout_sessions.user_id: integer -> varchar
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'stripe_checkout_sessions' 
                AND column_name = 'user_id' 
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE stripe_checkout_sessions ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;
            END IF;
        END $$;
    """)

    # 4. errands.user_id: integer -> varchar (if applicable)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'errands' 
                AND column_name = 'user_id' 
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE errands ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    pass
