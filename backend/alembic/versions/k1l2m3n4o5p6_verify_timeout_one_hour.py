"""raise default TRE verification wait from 10 minutes to 1 hour

verify_retries × verify_interval is the maximum wait. seed_defaults only inserts
missing settings, so existing databases keep the old value unless updated here.
Only rows still at the old default (10) are changed — a value set by an admin stays.

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-09-29
"""
from alembic import op

revision = 'k1l2m3n4o5p6'
down_revision = 'j1k2l3m4n5o6'
branch_labels = None
depends_on = None

_DESCRIPTION_NEW = ("How many times to poll S3 waiting for TRE to place the checksum confirmation file. "
                    "Maximum wait = this × verify_interval (default 60 × 60 s = 1 hour)")
_DESCRIPTION_OLD = "How many times to poll S3 waiting for TRE to place the checksum confirmation file"


def upgrade():
    op.execute(f"UPDATE settings SET value = '60', updated_at = now() WHERE key = 'verify_retries' AND value = '10'")
    op.execute(f"UPDATE settings SET description = '{_DESCRIPTION_NEW}' WHERE key = 'verify_retries'")


def downgrade():
    op.execute(f"UPDATE settings SET value = '10', updated_at = now() WHERE key = 'verify_retries' AND value = '60'")
    op.execute(f"UPDATE settings SET description = '{_DESCRIPTION_OLD}' WHERE key = 'verify_retries'")
