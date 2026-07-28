"""add checksum_chunk_size_mb setting

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-07-28

"""
from datetime import datetime
from alembic import op

revision = 'i1j2k3l4m5n6'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        f"INSERT INTO settings (key, value, category, description, updated_at) "
        f"VALUES ('checksum_chunk_size_mb', '5', 'checksum', "
        f"'Read chunk size in MB used when computing SHA256 checksums. Larger values (e.g. 32-64) speed up checksumming of large files over network shares. Avoid going above 256.', "
        f"'{datetime.now()}') ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'checksum_chunk_size_mb'")
