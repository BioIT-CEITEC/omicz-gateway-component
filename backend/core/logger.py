import logging
import os
from logging.handlers import RotatingFileHandler

from core.config import settings

# Base directory where all log folders will be created
# Inside Docker this maps to the host's ./logs/ via volume mount
LOGS_BASE_DIR = "/app/logs"


def get_logger(service_name: str) -> logging.Logger:
    """
    Returns a logger for the given service name.

    Usage:
        from core.logger import get_logger
        logger = get_logger("watcher")

    This creates:
        /app/logs/watcher/watcher.log   ← on Docker (maps to ./logs/watcher/ on host)

    Each call with the same name returns the same logger (Python caches them),
    so you can safely call get_logger("watcher") in multiple files — handlers
    won't be duplicated.
    """

    logger = logging.getLogger(service_name)

    # If this logger already has handlers, it was already configured — return as-is
    # This prevents adding duplicate handlers if get_logger() is called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(settings.LOG_LEVEL)

    # ── Format ────────────────────────────────────────────────────────────────
    # Example output:
    #   2026-04-30 12:00:01 | INFO     | watcher:51 | new run detected: run_001
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Handler 1: stdout (Docker logs still work) ────────────────────────────
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # ── Handler 2: rotating file ──────────────────────────────────────────────
    # Each service gets its own folder:  /app/logs/<service_name>/
    log_dir  = os.path.join(LOGS_BASE_DIR, service_name)
    log_file = os.path.join(log_dir, f"{service_name}.log")

    # Create the folder if it doesn't exist yet
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB per file
        backupCount=3,              # keep .log, .log.1, .log.2, .log.3
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    return logger
