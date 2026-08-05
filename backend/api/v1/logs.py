import os
import re
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

LOG_ROOT = "/app/logs"

# Only allow simple service names: letters, digits, hyphens, underscores
_SAFE_SERVICE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _safe_service_dir(service: str) -> str:
    """
    Validate the service name and return the resolved path.
    Raises HTTPException if the name is invalid or resolves outside LOG_ROOT.
    """
    if not _SAFE_SERVICE.match(service):
        raise HTTPException(status_code=400, detail="Invalid service name")
    service_dir = os.path.join(LOG_ROOT, service)
    # Resolve symlinks and ../ sequences, then confirm we're still inside LOG_ROOT
    real_service = os.path.realpath(service_dir)
    real_root    = os.path.realpath(LOG_ROOT)
    if not real_service.startswith(real_root + os.sep) and real_service != real_root:
        raise HTTPException(status_code=400, detail="Invalid service name")
    return service_dir


def _read_last_lines(service: str, n: int) -> list[str]:
    service_dir = _safe_service_dir(service)
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
        if not _SAFE_SERVICE.match(d):
            continue
        service_dir = os.path.join(LOG_ROOT, d)
        if not os.path.isdir(service_dir):
            continue
        log_file = os.path.join(service_dir, f"{d}.log")
        if os.path.isfile(log_file) and os.path.getsize(log_file) > 0:
            services.append(d)
    return {"services": services}


@router.get("/{service}")
def get_log(service: str, lines: int = Query(default=200, ge=1, le=5000)):
    service_dir = _safe_service_dir(service)
    if not os.path.isdir(service_dir):
        raise HTTPException(status_code=404, detail=f"No log directory for service '{service}'")
    content = _read_last_lines(service, lines)
    return {"service": service, "lines": content}
