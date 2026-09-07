"""Add pilot profile fields to users table

Revision ID: 005_pilot_profile_fields
Revises: 004_pilot_locations
Create Date: 2026-01-07 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "005_pilot_profile_fields"
down_revision = "004_pilot_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add profile, address and vehicle columns to users table"""
    # Add profile image URL
    op.add_column("users", sa.Column("profile_image_url", sa.String(), nullable=True))

    # Add date of birth
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))

    # Add additional address fields
    op.add_column("users", sa.Column("street_address", sa.String(), nullable=True))
    op.add_column("users", sa.Column("state_province", sa.String(), nullable=True))

    # Add vehicle information columns
    op.add_column("users", sa.Column("vehicle_type", sa.String(), nullable=True))
    op.add_column("users", sa.Column("vehicle_make", sa.String(), nullable=True))
    op.add_column("users", sa.Column("vehicle_model", sa.String(), nullable=True))
    op.add_column("users", sa.Column("vehicle_year", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("license_plate", sa.String(), nullable=True))
    op.add_column("users", sa.Column("insurance_provider", sa.String(), nullable=True))
    op.add_column("users", sa.Column("insurance_expiry", sa.Date(), nullable=True))

    # Add rating field
    op.add_column("users", sa.Column("rating", sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove added columns"""
    op.drop_column("users", "rating")
    op.drop_column("users", "insurance_expiry")
    op.drop_column("users", "insurance_provider")
    op.drop_column("users", "license_plate")
    op.drop_column("users", "vehicle_year")
    op.drop_column("users", "vehicle_model")
    op.drop_column("users", "vehicle_make")
    op.drop_column("users", "vehicle_type")
    op.drop_column("users", "state_province")
    op.drop_column("users", "street_address")
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "profile_image_url")
