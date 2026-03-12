"""Fix datetime from UTC to local timezone (Peru UTC-5)

Revision ID: fix_datetime_utc_local
Revises: ec6c9ecfe7a5_add_role_based_permissions_to_settings
Create Date: 2026-03-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import timedelta


# revision identifiers, used by Alembic.
revision = 'fix_datetime_utc_local'
down_revision = 'ec6c9ecfe7a5'
branch_labels = None
depends_on = None


def upgrade():
    """Adjust all UTC timestamps to local time (Peru timezone UTC-5)."""
    # Note: This migration assumes Peru timezone (UTC-5)
    # If you're in a different timezone, adjust the hours offset accordingly
    
    conn = op.get_bind()
    
    # For SQLite, use datetime() function with modifier
    # Adjust Sale created_at timestamps
    conn.execute(sa.text("""
        UPDATE sale 
        SET created_at = datetime(created_at, '-5 hours')
        WHERE created_at IS NOT NULL
    """))
    
    # Adjust Payment created_at timestamps
    conn.execute(sa.text("""
        UPDATE payment 
        SET created_at = datetime(created_at, '-5 hours')
        WHERE created_at IS NOT NULL
    """))


def downgrade():
    """Revert timestamps back to UTC (not recommended)."""
    conn = op.get_bind()
    
    # This would revert the adjustment, but should only be used if reverting the code changes
    conn.execute(sa.text("""
        UPDATE sale 
        SET created_at = datetime(created_at, '+5 hours')
        WHERE created_at IS NOT NULL
    """))
    
    conn.execute(sa.text("""
        UPDATE payment 
        SET created_at = datetime(created_at, '+5 hours')
        WHERE created_at IS NOT NULL
    """))
