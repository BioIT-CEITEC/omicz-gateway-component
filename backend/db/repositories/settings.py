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
        "value": "256",
        "category": "checksum",
        "description": "Read chunk size in MB used when computing SHA256 checksums. Larger values (e.g. 32–64) speed up checksumming of large files over network shares. Maximum 4096 MB (4 GB).",
    },
    # ── Upload ────────────────────────────────────────────────────────────────
    {
        "key": "upload_engine",
        "value": "boto3",
        "category": "upload",
        "description": "Library that uploads run files to S3: boto3 (Python, one file at a time, live byte progress) or s5cmd (Go binary, several files at once, progress per finished file)",
    },
    {
        "key": "pipeline_parallel_runs",
        "value": "1",
        "category": "upload",
        "description": "Runs the worker uploads at the same time. 1 = one run at a time; 2 lets a small run start while a large one is still uploading (they share the network link). Checksumming has its own setting. The worker applies a change within 15 seconds",
    },
    {
        "key": "pipeline_parallel_checksums",
        "value": "1",
        "category": "upload",
        "description": "Finished runs the worker checksums at the same time. Checksumming has its own slots, so a run is hashed while others upload and its upload starts right away when an upload slot frees. The worker applies a change within 15 seconds",
    },
    {
        "key": "upload_fast_lane_mb",
        "value": "256",
        "category": "upload",
        "description": "After the checksum, a run with at most this many MB left to send is uploaded at once instead of waiting for an upload slot (e.g. a directory-stability run whose folders were sent during acquisition: only root files and the .CHECKSUM remain). 0 = always wait for a slot",
    },
    {
        "key": "upload_s5cmd_workers",
        "value": "4",
        "category": "upload",
        "description": "Files uploaded at the same time when the upload engine is s5cmd. Many small files (e.g. Illumina BCL) upload faster with more workers",
    },
    {
        "key": "upload_s5cmd_concurrency",
        "value": "4",
        "category": "upload",
        "description": "Parts of one large file uploaded at the same time when the upload engine is s5cmd. Open connections = workers × this",
    },
    {
        "key": "upload_s5cmd_part_size_mb",
        "value": "16",
        "category": "upload",
        "description": "Size in MB of each part of a large file when the upload engine is s5cmd (5–5120). Larger parts suit very large files; s5cmd holds about workers × concurrency × part size in memory",
    },
    {
        "key": "upload_max_attempts",
        "value": "5",
        "category": "upload",
        "description": "Maximum number of retry attempts when uploading a single file to S3 before giving up",
    },
    {
        "key": "upload_retry_backoff_max",
        "value": "60",
        "category": "upload",
        "description": "Maximum wait time (seconds) between consecutive upload retry attempts (exponential backoff capped here)",
    },
    # ── Verification ──────────────────────────────────────────────────────────
    {
        "key": "verify_retries",
        "value": "60",
        "category": "verification",
        "description": "How many times to poll S3 waiting for TRE to place the checksum confirmation file. Maximum wait = this × verify_interval (default 60 × 60 s = 1 hour)",
    },
    {
        "key": "verify_minutes_per_100gb",
        "value": "24",
        "category": "verification",
        "description": "Extra minutes of TRE wait per 100 GB of run data, on top of verify_retries × verify_interval (the TRE re-hashes all data before confirming). Default 24: 250 GB → 2 h, 1 TB → 5 h in total",
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
        "value": "8",
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
    {
        "key": "dir_stability_poll_interval",
        "value": "60",
        "category": "watcher",
        "description": "Seconds between directory stability checks. Each check walks every running run folder of instruments using the Directory Stability method",
    },
    {
        "key": "reopen_scan_interval",
        "value": "600",
        "category": "watcher",
        "description": "Seconds between checks of completed runs for new files (a new sample or run added to a finished project). A run with new files goes back to running and finishes by the instrument's own completion rule. Each check walks the folders of recently completed runs. 0 = never reopen completed runs",
    },
    {
        "key": "reopen_watch_days",
        "value": "30",
        "category": "watcher",
        "description": "Completed runs are checked for new files for this many days after they completed. Older runs are left alone",
    },
    # ── Backup ────────────────────────────────────────────────────────────────
    {
        "key": "backup_interval_days",
        "value": "2",
        "category": "backup",
        "description": "Days between automatic database backups",
    },
    {
        "key": "backup_retention_count",
        "value": "10",
        "category": "backup",
        "description": "Number of most recent database backups to keep; older ones are deleted automatically",
    },
]


# settings that take one of a fixed set of values instead of a number
CHOICES = {
    "upload_engine": ["boto3", "s5cmd"],
}


# numeric settings with hard limits (inclusive) — values outside are refused
RANGES = {
    "pipeline_parallel_runs":    (1, 8),
    "pipeline_parallel_checksums": (1, 8),
    "upload_fast_lane_mb":       (0, 102400),
    "upload_s5cmd_workers":      (1, 256),
    "upload_s5cmd_concurrency":  (1, 64),
    "upload_s5cmd_part_size_mb": (5, 5120),   # S3 multipart limits: 5 MiB to 5 GiB per part
    "reopen_scan_interval":      (0, 86400),
    "reopen_watch_days":         (1, 3650),
}


class InvalidSettingValue(ValueError):
    pass


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


def validate_value(key: str, value) -> None:
    """Raise InvalidSettingValue when value is outside the key's CHOICES or RANGES."""
    if key in CHOICES and str(value) not in CHOICES[key]:
        raise InvalidSettingValue(f"'{value}' is not valid for {key} — choose one of: {', '.join(CHOICES[key])}")
    if key in RANGES:
        lo, hi = RANGES[key]
        try:
            ok = lo <= int(str(value)) <= hi
        except ValueError:
            ok = False
        if not ok:
            raise InvalidSettingValue(f"'{value}' is not valid for {key} — enter a whole number from {lo} to {hi}")


def upsert(key: str, value: str, db: Session) -> Settings:
    s = db.query(Settings).filter(Settings.key == key).first()
    if not s:
        raise ValueError(f"Unknown setting key: '{key}'")
    validate_value(key, value)
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


def get_setting_str(key: str, default: str) -> str:
    """Like get_setting_int, for text settings such as upload_engine."""
    try:
        from db.session import SESSION_LOCAL
        session = SESSION_LOCAL()
        try:
            row = session.query(Settings).filter(Settings.key == key).first()
            return row.value if row else default
        finally:
            session.close()
    except Exception:
        return default
