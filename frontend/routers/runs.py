import os
import httpx
from datetime import datetime
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse
from routers.settings import get_setting_value


_TERMINAL = {"completed", "failed", "move_failed", "verify_failed", "running_finished"}


def _fmt_seconds(delta: int) -> str:
    if delta < 60: return f"{delta}s"
    if delta < 3600:
        m, s = divmod(delta, 60)
        return f"{m}m {s}s"
    h, rem = divmod(delta, 3600)
    return f"{h}h {rem // 60}m"


def _fmt_duration(run: dict) -> str | None:
    """Total duration (created→updated) only for terminal statuses."""
    if run.get("status") not in _TERMINAL:
        return None
    try:
        created = datetime.fromisoformat(run["created_at"])
        updated = datetime.fromisoformat(run["updated_at"])
        delta = int((updated - created).total_seconds())
        return _fmt_seconds(delta) if delta >= 0 else None
    except Exception:
        return None


def _fmt_sequencing_duration(run: dict, history: list) -> str | None:
    """Time from run creation to the first running_finished history entry."""
    finished_at = next(
        (e["created_at"] for e in history if e.get("status") == "running_finished"),
        None,
    )
    if not finished_at:
        return None
    try:
        created  = datetime.fromisoformat(run["created_at"])
        finished = datetime.fromisoformat(finished_at)
        delta    = int((finished - created).total_seconds())
        return _fmt_seconds(delta) if delta >= 0 else None
    except Exception:
        return None

def _page_size() -> int:
    return get_setting_value("pagination_page_size", 20)

router = APIRouter()
from shared_templates import templates

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def safe_json(response: httpx.Response, fallback=None):
    try:
        return response.json()
    except Exception:
        return fallback


# ── LIST 
@router.get("/")
def list_runs(request: Request, skip: int = 0, limit: int | None = None, status: list[str] | None = Query(default=None), search: str | None = None, order: str = "desc", sequencer_uuid: str | None = None):
    if limit is None: limit = _page_size()
    if order not in ("asc", "desc"): order = "desc"
    params: dict = {"skip": skip, "limit": limit, "order": order}
    if status:
        params["status"] = status
    if search:
        params["search"] = search
    if sequencer_uuid:
        params["sequencer_uuid"] = sequencer_uuid
    response = httpx.get(f"{BACKEND_URL}/runs/", params=params)
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    # Fetch all sequencers for the machine filter dropdown
    seq_list_resp = httpx.get(f"{BACKEND_URL}/sequencers/", params={"skip": 0, "limit": 200})
    sequencers = safe_json(seq_list_resp, fallback={"results": []}).get("results", [])
    # Resolve name from uuid for the banner (use cached list first)
    sequencer_name = next((s["name"] for s in sequencers if str(s["uuid"]) == sequencer_uuid), None)
    return templates.TemplateResponse(request, "runs/list.html", {
        "data": data,
        "status_filter": status or [],
        "search_query": search or "",
        "order": order,
        "sequencer_uuid": sequencer_uuid or "",
        "sequencer_name": sequencer_name or "",
        "sequencers": sequencers,
    })


# ── DETAIL
@router.get("/{uuid}")
def detail_run(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/runs/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    run = safe_json(response, fallback={})
    history_response = httpx.get(f"{BACKEND_URL}/runs/{uuid}/history")
    history = safe_json(history_response, fallback=[])
    return templates.TemplateResponse(request, "runs/detail.html", {
        "run": run,
        "history": history,
        "duration": _fmt_duration(run),
        "sequencing_duration": _fmt_sequencing_duration(run, history),
        "active_refresh": get_setting_value("active_refresh_interval", 5),
        "idle_refresh":   get_setting_value("idle_refresh_interval", 120),
    })


# ── HISTORY DATA (polled by JS on detail page)
@router.get("/{uuid}/history-data")
def history_data(uuid: str):
    run_res     = httpx.get(f"{BACKEND_URL}/runs/{uuid}")
    history_res = httpx.get(f"{BACKEND_URL}/runs/{uuid}/history")
    run     = safe_json(run_res,     fallback={})
    history = safe_json(history_res, fallback=[])
    return {"status": run.get("status"), "progress": run.get("progress"), "progress_updated_at": run.get("updated_at"), "history": history}


# ── QUEUE
@router.get("/queue/view")
def queue_view(request: Request, skip: int = 0, limit: int | None = None):
    if limit is None: limit = _page_size()
    response = httpx.get(f"{BACKEND_URL}/runs/queue", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    failed = safe_json(httpx.get(f"{BACKEND_URL}/runs/failed"), fallback=[])
    return templates.TemplateResponse(request, "runs/queue.html", {"data": data, "failed": failed})


# ── START UPLOAD (manual trigger for sent_to_tre=manual)
@router.post("/{uuid}/start-upload")
def start_upload(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/runs/{uuid}/start-upload")
    return RedirectResponse(url=f"/acquisition-runs/{uuid}", status_code=303)


# ── CANCEL UPLOAD (force moving → move_failed)
@router.post("/{uuid}/cancel-upload")
def cancel_upload(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/runs/{uuid}/cancel-upload")
    return RedirectResponse(url=f"/acquisition-runs/{uuid}", status_code=303)


# ── RECHECK (delete checksum + re-checksum + re-upload + re-verify)
@router.post("/{uuid}/recheck")
def recheck_run(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/runs/{uuid}/recheck")
    return RedirectResponse(url=f"/acquisition-runs/{uuid}", status_code=303)


# ── DELETE
@router.post("/{uuid}/delete")
def delete_run(request: Request, uuid: str, next: str = "/acquisition-runs/"):
    httpx.delete(f"{BACKEND_URL}/runs/{uuid}")
    return RedirectResponse(url=next, status_code=303)
