from datetime import datetime
from sqlalchemy.orm import Session

from db.models.settings import Settings

DEFAULTS = [
    # ── UI Timings ────────────────────────────────────────────────────────────
    {
        "key": "active_refresh_interval",
        "value": "5",
        "category": "ui",
        "description": "How often (seconds) the run detail page auto-refreshes while checksumming, moving, verifying, or queued",
    },
    {
        "key": "idle_refresh_interval",
        "value": "120",
        "category": "ui",
        "description": "How often (seconds) the run detail page auto-refreshes while the run is still sequencing (running status)",
    },
    {
        "key": "containers_refresh_interval",
        "value": "10",
        "category": "ui",
        "description": "How often (seconds) the Containers page auto-refreshes",
    },
    # ── Checksum ──────────────────────────────────────────────────────────────
    {
        "key": "checksum_chunk_size_mb",
        "value": "5",
        "category": "checksum",
        "description": "Read chunk size in MB used when computing SHA256 checksums. Larger values (e.g. 32–64) speed up checksumming of large files over network shares. Maximum 4096 MB (4 GB).",
    },
    # ── Upload ────────────────────────────────────────────────────────────────
    {
        "key": "upload_max_attempts",
        "value": "5",
        "category": "upload",
        "description": "Maximum number of retry attempts when uploading a single file to S3 before giving up",
    },
    {
        "key": "upload_retry_backoff_max",
        "value": "30",
        "category": "upload",
        "description": "Maximum wait time (seconds) between consecutive upload retry attempts (exponential backoff capped here)",
    },
    # ── Verification ──────────────────────────────────────────────────────────
    {
        "key": "verify_retries",
        "value": "10",
        "category": "verification",
        "description": "How many times to poll S3 waiting for TRE to place the checksum confirmation file",
    },
    {
        "key": "verify_interval",
        "value": "60",
        "category": "verification",
        "description": "Seconds to wait between each S3 verification poll attempt",
    },
    # ── Logs ──────────────────────────────────────────────────────────────────
    {
        "key": "log_lines_count",
        "value": "500",
        "category": "logs",
        "description": "Number of log lines to show per service in the Logs viewer",
    },
    {
        "key": "log_viewer_refresh_interval",
        "value": "10",
        "category": "logs",
        "description": "How often (seconds) the Logs viewer auto-refreshes",
    },
    # ── Pagination ────────────────────────────────────────────────────────────
    {
        "key": "pagination_page_size",
        "value": "20",
        "category": "pagination",
        "description": "Number of items shown per page on all list pages (Runs, Sequencers, Users, Sequencer Types)",
    },
    # ── Watcher ───────────────────────────────────────────────────────────────
    {
        "key": "run_detection_delay",
        "value": "15",
        "category": "watcher",
        "description": "Seconds to wait after a new run folder appears before registering it (gives the OS time to finish renaming)",
    },
    {
        "key": "sequencer_check_interval",
        "value": "60",
        "category": "watcher",
        "description": "Seconds between database polls for newly added sequencers (no watcher restart needed after adding a sequencer)",
    },
]


def seed_defaults(db: Session) -> None:
    """Insert default settings that do not already exist. Safe to call on every startup."""
    for row in DEFAULTS:
        if not db.query(Settings).filter(Settings.key == row["key"]).first():
            db.add(Settings(
                key=row["key"],
                value=row["value"],
                description=row["description"],
                category=row["category"],
                updated_at=datetime.now(),
            ))
    db.commit()


def get_all(db: Session) -> list[Settings]:
    return db.query(Settings).order_by(Settings.category, Settings.key).all()


def get_by_key(key: str, db: Session) -> Settings | None:
    return db.query(Settings).filter(Settings.key == key).first()


def upsert(key: str, value: str, db: Session) -> Settings:
    s = db.query(Settings).filter(Settings.key == key).first()
    if not s:
        raise ValueError(f"Unknown setting key: '{key}'")
    s.value = str(value)
    s.updated_at = datetime.now()
    db.commit()
    db.refresh(s)
    return s


def get_setting_int(key: str, default: int) -> int:
    """
    Read a single setting value as int.
    Opens its own short-lived DB session — safe to call from any service.
    Falls back to `default` on any error (missing table, bad value, etc.).
    """
    try:
        from db.session import SESSION_LOCAL
        session = SESSION_LOCAL()
        try:
            row = session.query(Settings).filter(Settings.key == key).first()
            return int(row.value) if row else default
        finally:
            session.close()
    except Exception:
        return default
