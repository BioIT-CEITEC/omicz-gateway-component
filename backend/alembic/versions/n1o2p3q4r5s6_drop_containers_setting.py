"""settings: drop containers_refresh_interval (Containers page removed)

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-11-05
"""
from alembic import op

revision = 'n1o2p3q4r5s6'
down_revision = 'm1n2o3p4q5r6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM settings WHERE key = 'containers_refresh_interval'")


def downgrade():
    op.execute(
        "INSERT INTO settings (key, value, category, description) "
        "VALUES ('containers_refresh_interval', '10', 'ui', "
        "'How often (seconds) the Containers page auto-refreshes') "
        "ON CONFLICT (key) DO NOTHING"
    )
