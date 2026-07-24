"""add settings table

Revision ID: g1h2i3j4k5l6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-24

"""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = 'g1h2i3j4k5l6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

DEFAULTS = [
    ("active_refresh_interval",     "5",   "ui",           "How often (seconds) the run detail page auto-refreshes while checksumming, moving, verifying, or queued"),
    ("idle_refresh_interval",       "120", "ui",           "How often (seconds) the run detail page auto-refreshes while the run is still sequencing (running status)"),
    ("containers_refresh_interval", "10",  "ui",           "How often (seconds) the Containers page auto-refreshes"),
    ("k8s_log_refresh_interval",    "10",  "ui",           "How often (seconds) the K8s Proxy log auto-refreshes"),
    ("upload_max_attempts",         "5",   "upload",       "Maximum number of retry attempts when uploading a single file to S3 before giving up"),
    ("upload_retry_backoff_max",    "30",  "upload",       "Maximum wait time (seconds) between consecutive upload retry attempts"),
    ("verify_retries",              "10",  "verification", "How many times to poll S3 waiting for TRE to place the checksum confirmation file"),
    ("verify_interval",             "60",  "verification", "Seconds to wait between each S3 verification poll attempt"),
    ("run_detection_delay",         "15",  "watcher",      "Seconds to wait after a new run folder appears before registering it"),
    ("sequencer_check_interval",    "60",  "watcher",      "Seconds between database polls for newly added sequencers"),
]


def upgrade() -> None:
    settings_table = op.create_table(
        "settings",
        sa.Column("key",         sa.String(),  nullable=False),
        sa.Column("value",       sa.String(),  nullable=False),
        sa.Column("description", sa.Text(),    nullable=False, server_default=""),
        sa.Column("category",    sa.String(),  nullable=False, server_default="general"),
        sa.Column("updated_at",  sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    now = datetime.now()
    op.bulk_insert(settings_table, [
        {"key": k, "value": v, "category": c, "description": d, "updated_at": now}
        for k, v, c, d in DEFAULTS
    ])


def downgrade() -> None:
    op.drop_table("settings")
