"""add checksum_chunk_size_mb setting

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-07-28

"""
from alembic import op
import sqlalchemy as sa

revision = 'i1j2k3l4m5n6'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO settings (key, value, category, description, updated_at) "
            "VALUES (:key, :value, :category, :description, NOW()) "
            "ON CONFLICT DO NOTHING"
        ).bindparams(
            key="checksum_chunk_size_mb",
            value="256",
            category="checksum",
            description="Read chunk size in MB used when computing SHA256 checksums. Larger values (e.g. 32-64) speed up checksumming of large files over network shares. Avoid going above 256.",
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'checksum_chunk_size_mb'")
