"""alter pilot_status_changed_by to uuid

Revision ID: 021_pilot_status_by_uuid
Revises: 020_user_id_to_varchar
Create Date: 2026-09-09 13:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_pilot_status_by_uuid"
down_revision: Union[str, Sequence[str], None] = "020_user_id_to_varchar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'users' 
                AND column_name = 'pilot_status_changed_by' 
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE users ALTER COLUMN pilot_status_changed_by TYPE UUID USING NULL;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    pass
