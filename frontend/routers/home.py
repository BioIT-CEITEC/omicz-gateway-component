import os
import httpx
from collections import Counter
from datetime import datetime, timedelta
from fastapi import APIRouter, Request

router = APIRouter()
from shared_templates import templates

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
    seq_data     = _get("/sequencers/", {"limit": 50}) or {}
    sequencers   = seq_data.get("results", [])
    seq_active   = sum(1 for s in sequencers if s.get("status") == "active")
    seq_total    = len(sequencers)

    # recent runs (last 6 for the list)
    recent_data  = _get("/runs/", {"limit": 6, "order": "desc"}) or {}
    recent_runs  = recent_data.get("results", [])

    # chart data: fetch last 50 runs for analysis
    chart_raw = _get("/runs/", {"limit": 50, "order": "desc"}) or {}
    chart_runs = chart_raw.get("results", [])

    # daily activity — last 14 days
    today = datetime.now().date()
    days_14 = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    daily_counts = Counter(r["created_at"][:10] for r in chart_runs)
    daily_labels = [d[5:].replace("-", "/") for d in days_14]  # MM/DD
    daily_values = [daily_counts.get(d, 0) for d in days_14]

    # runs by sequencer (top 6, from chart_runs)
    seq_run_counts = Counter(r["sequencer_name"] for r in chart_runs if r.get("sequencer_name"))
    top_seqs = seq_run_counts.most_common(6)
    seq_bar_labels = [s[0] for s in top_seqs]
    seq_bar_values = [s[1] for s in top_seqs]

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
        "total":           sequencing + ready_to_upload + in_pipeline + failed + completed,
    }

    # mount health
    mount_raw = _get("/sequencers/mount-status") or {}
    mount_warnings = [m for m in mount_raw.get("mounts", []) if not m.get("accessible", True)]

    return templates.TemplateResponse(request, "home.html", {
        "stats": stats,
        "recent_runs": recent_runs,
        "seq_names": seq_names,
        "daily_labels": daily_labels,
        "daily_values": daily_values,
        "seq_bar_labels": seq_bar_labels,
        "seq_bar_values": seq_bar_values,
        "mount_warnings": mount_warnings,
    })
