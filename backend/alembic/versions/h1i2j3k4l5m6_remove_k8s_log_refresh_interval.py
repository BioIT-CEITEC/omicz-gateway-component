"""remove k8s_log_refresh_interval setting

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-07-28

"""
from alembic import op

revision = 'h1i2j3k4l5m6'
down_revision = '0b237ed2d834'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'k8s_log_refresh_interval'")


def downgrade() -> None:
    import sqlalchemy as sa
    op.execute(
        sa.text(
            "INSERT INTO settings (key, value, category, description, updated_at) "
            "VALUES (:key, :value, :category, :description, NOW())"
        ),
        {
            "key": "k8s_log_refresh_interval",
            "value": "10",
            "category": "ui",
            "description": "How often (seconds) the K8s Proxy log auto-refreshes",
        },
    )
