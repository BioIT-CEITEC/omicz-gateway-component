import datetime
import logging
import os
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

LOGS_BASE_DIR = "/app/logs"


def get_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(service_name)

    if logger.handlers:
        return logger

    log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    logger.setLevel(log_level)

    class _TZFormatter(logging.Formatter):
        _tz = ZoneInfo(os.getenv("LOG_TIMEZONE", "Europe/Prague"))

        def formatTime(self, record, datefmt=None):
            dt = datetime.datetime.fromtimestamp(record.created, tz=self._tz)
            return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

    formatter = _TZFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    log_dir  = os.path.join(LOGS_BASE_DIR, service_name)
    log_file = os.path.join(log_dir, f"{service_name}.log")
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    return logger
