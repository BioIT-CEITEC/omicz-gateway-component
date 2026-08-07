import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

# allow imports from the backend folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from core.logger import get_logger
from db.repositories.settings import get_setting_int

logger = get_logger("backup")

BACKUP_DIR         = "/app/backups"
_CHECK_INTERVAL     = 60  # seconds between due-checks
_INTERVAL_DAYS_DEFAULT   = 2
_RETENTION_COUNT_DEFAULT = 10
_FILENAME_RE = re.compile(r"^backup_(\d{8}_\d{6})\.sql\.gz$")


def _existing_backups() -> list[str]:
    """Backup filenames, oldest → newest (timestamp is lexicographically sortable)."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted(f for f in os.listdir(BACKUP_DIR) if _FILENAME_RE.match(f))


def _last_backup_time() -> datetime | None:
    backups = _existing_backups()
    if not backups:
        return None
    match = _FILENAME_RE.match(backups[-1])
    return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)


def _prune_old_backups() -> None:
    retention = get_setting_int("backup_retention_count", _RETENTION_COUNT_DEFAULT)
    backups   = _existing_backups()
    excess    = len(backups) - retention
    for name in backups[:max(0, excess)]:
        path = os.path.join(BACKUP_DIR, name)
        try:
            os.remove(path)
            logger.info(f"pruned old backup: {name}")
        except OSError as e:
            logger.error(f"failed to prune backup {name}: {e}")


def run_backup() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{stamp}.sql.gz"
    path     = os.path.join(BACKUP_DIR, filename)
    tmp_path = path + ".tmp"

    env = os.environ.copy()
    env["PGPASSWORD"] = settings.POSTGRES_PASSWORD

    dump_cmd = [
        "pg_dump",
        "-h", settings.POSTGRES_HOST,
        "-p", str(settings.POSTGRES_PORT),
        "-U", settings.POSTGRES_USERNAME,
        "-d", settings.POSTGRES_DB,
        "--no-owner", "--no-privileges",
    ]

    logger.info(f"starting database backup -> {filename}")
    dump = None
    try:
        with open(tmp_path, "wb") as out_file:
            dump = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, env=env)
            gzip_proc = subprocess.Popen(["gzip"], stdin=dump.stdout, stdout=out_file)
            dump.stdout.close()  # let gzip see EOF when pg_dump exits
            gzip_proc.communicate()
            dump.wait()

        if dump.returncode != 0:
            raise RuntimeError(f"pg_dump exited with code {dump.returncode}")

        os.replace(tmp_path, path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        logger.info(f"backup complete: {filename} ({size_mb:.1f} MB)")
    except Exception as e:
        logger.error(f"backup failed: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return

    _prune_old_backups()


def start() -> None:
    logger.info("backup service started. press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(_CHECK_INTERVAL)
            interval_days = get_setting_int("backup_interval_days", _INTERVAL_DAYS_DEFAULT)
            last_backup   = _last_backup_time()
            due = (
                last_backup is None
                or (datetime.now(timezone.utc) - last_backup).total_seconds() >= interval_days * 86400
            )
            if due:
                run_backup()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    start()
