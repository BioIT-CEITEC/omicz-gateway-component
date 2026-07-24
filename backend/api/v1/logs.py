import os
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

LOG_ROOT = "/app/logs"


def _read_last_lines(service: str, n: int) -> list[str]:
    """
    Read the last n lines from a service's log files.
    Reads backup files (log.2, log.1) before the main file so older
    entries come first and we always return the most recent n lines.
    """
    service_dir = os.path.join(LOG_ROOT, service)
    main_file   = os.path.join(service_dir, f"{service}.log")
    all_lines   = []

    # rotated backups first (oldest → newest), then main file
    for path in [main_file + ".2", main_file + ".1", main_file]:
        if os.path.isfile(path):
            try:
                with open(path, "r", errors="replace") as fh:
                    all_lines.extend(fh.readlines())
            except OSError:
                pass

    return [line.rstrip("\n") for line in all_lines[-n:]]


@router.get("/")
def list_log_services():
    if not os.path.isdir(LOG_ROOT):
        return {"services": []}
    services = []
    for d in sorted(os.listdir(LOG_ROOT)):
        service_dir = os.path.join(LOG_ROOT, d)
        if not os.path.isdir(service_dir):
            continue
        log_file = os.path.join(service_dir, f"{d}.log")
        # only include services whose log file exists and has content
        if os.path.isfile(log_file) and os.path.getsize(log_file) > 0:
            services.append(d)
    return {"services": services}


@router.get("/{service}")
def get_log(service: str, lines: int = Query(default=200, ge=1, le=5000)):
    service_dir = os.path.join(LOG_ROOT, service)
    if not os.path.isdir(service_dir):
        raise HTTPException(status_code=404, detail=f"No log directory for service '{service}'")
    content = _read_last_lines(service, lines)
    return {"service": service, "lines": content}
