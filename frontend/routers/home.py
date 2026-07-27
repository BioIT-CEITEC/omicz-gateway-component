import os
import httpx
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def _get(path: str, params: dict | None = None):
    try:
        r = httpx.get(f"{BACKEND_URL}{path}", params=params, timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@router.get("/")
def home(request: Request):
    # fetch counts by status group
    def count(*statuses):
        total = 0
        for s in statuses:
            data = _get("/runs/", {"status": s, "limit": 1})
            if data:
                total += data.get("total", 0)
        return total

    sequencing       = count("running")
    ready_to_upload  = count("running_finished")
    in_pipeline      = count("queued", "checksumming", "moving", "verifying")
    failed           = count("move_failed", "verify_failed", "failed")
    completed        = count("completed")

    # sequencer stats
    seq_data     = _get("/sequencers/", {"limit": 100}) or {}
    sequencers   = seq_data.get("results", [])
    seq_active   = sum(1 for s in sequencers if s.get("status") == "active")
    seq_total    = len(sequencers)

    # recent runs (last 5)
    recent_data  = _get("/runs/", {"limit": 5, "order": "desc"}) or {}
    recent_runs  = recent_data.get("results", [])

    # sequencer name lookup for recent runs
    seq_names = {s["uuid"]: s["name"] for s in sequencers}

    stats = {
        "sequencing":      sequencing,
        "ready_to_upload": ready_to_upload,
        "in_pipeline":     in_pipeline,
        "failed":          failed,
        "completed":       completed,
        "seq_active":      seq_active,
        "seq_total":       seq_total,
    }

    return templates.TemplateResponse(request, "home.html", {
        "stats": stats,
        "recent_runs": recent_runs,
        "seq_names": seq_names,
    })
