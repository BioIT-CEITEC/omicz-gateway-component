import os
import httpx
from fastapi import APIRouter, Request, Query
from fastapi.templating import Jinja2Templates
from routers.settings import get_setting_value

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BACKEND_URL  = os.getenv("BACKEND_URL", "http://backend:8000")
FRONTEND_LOG = "/app/logs/frontend/frontend.log"


def _lines_count() -> int:
    return get_setting_value("log_lines_count", 500)


def _backend_services() -> list[str]:
    try:
        res = httpx.get(f"{BACKEND_URL}/logs/", timeout=5)
        if res.status_code == 200:
            return res.json().get("services", [])
    except Exception:
        pass
    return []


def _backend_log_lines(service: str, lines: int) -> list[str]:
    try:
        res = httpx.get(f"{BACKEND_URL}/logs/{service}", params={"lines": lines}, timeout=10)
        if res.status_code == 200:
            return res.json().get("lines", [])
    except Exception:
        pass
    return []


def _frontend_log_lines(lines: int) -> list[str]:
    try:
        all_lines = []
        for path in [FRONTEND_LOG + ".2", FRONTEND_LOG + ".1", FRONTEND_LOG]:
            if os.path.isfile(path):
                with open(path, "r", errors="replace") as fh:
                    all_lines.extend(fh.readlines())
        return [line.rstrip("\n") for line in all_lines[-lines:]]
    except Exception:
        return []


def _get_lines(service: str, lines: int) -> list[str]:
    if service == "frontend":
        return _frontend_log_lines(lines)
    return _backend_log_lines(service, lines)


@router.get("/")
def logs_page(request: Request, service: str = "backend"):
    backend_services = _backend_services()
    all_services     = backend_services + (["frontend"] if "frontend" not in backend_services else [])
    # default to first available if requested service doesn't exist
    if service not in all_services and all_services:
        service = all_services[0]
    n               = _lines_count()
    refresh_interval = get_setting_value("log_viewer_refresh_interval", 10)
    lines           = _get_lines(service, n)
    return templates.TemplateResponse(request, "logs/index.html", {
        "services":         all_services,
        "active_service":   service,
        "lines":            lines,
        "lines_count":      n,
        "refresh_interval": refresh_interval,
    })


@router.get("/data/{service}")
def logs_data(service: str, lines: int = Query(default=None, ge=1, le=5000)):
    if lines is None:
        lines = _lines_count()
    return {"service": service, "lines": _get_lines(service, lines)}
