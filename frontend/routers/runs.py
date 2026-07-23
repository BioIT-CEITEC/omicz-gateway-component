import os
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def safe_json(response: httpx.Response, fallback=None):
    try:
        return response.json()
    except Exception:
        return fallback


# ── LIST 
@router.get("/")
def list_runs(request: Request, skip: int = 0, limit: int = 20):
    response = httpx.get(f"{BACKEND_URL}/runs/", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    return templates.TemplateResponse(request, "runs/list.html", {"data": data})


# ── DETAIL
@router.get("/{uuid}")
def detail_run(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/runs/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    run = safe_json(response, fallback={})
    history_response = httpx.get(f"{BACKEND_URL}/runs/{uuid}/history")
    history = safe_json(history_response, fallback=[])
    proxy_status = safe_json(httpx.get(f"{BACKEND_URL}/k8s-proxy/status"), fallback={"status": "unknown"})
    return templates.TemplateResponse(request, "runs/detail.html", {"run": run, "history": history, "proxy_status": proxy_status})


# ── HISTORY DATA (polled by JS on detail page)
@router.get("/{uuid}/history-data")
def history_data(uuid: str):
    run_res     = httpx.get(f"{BACKEND_URL}/runs/{uuid}")
    history_res = httpx.get(f"{BACKEND_URL}/runs/{uuid}/history")
    run     = safe_json(run_res,     fallback={})
    history = safe_json(history_res, fallback=[])
    return {"status": run.get("status"), "progress": run.get("progress"), "history": history}


# ── QUEUE
@router.get("/queue/view")
def queue_view(request: Request, skip: int = 0, limit: int = 20):
    response = httpx.get(f"{BACKEND_URL}/runs/queue", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    failed = safe_json(httpx.get(f"{BACKEND_URL}/runs/failed"), fallback=[])
    proxy_status = safe_json(httpx.get(f"{BACKEND_URL}/k8s-proxy/status"), fallback={"status": "unknown"})
    return templates.TemplateResponse(request, "runs/queue.html", {"data": data, "failed": failed, "proxy_status": proxy_status})


# ── START UPLOAD (manual trigger for sent_to_tre=manual)
@router.post("/{uuid}/start-upload")
def start_upload(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/runs/{uuid}/start-upload")
    return RedirectResponse(url=f"/runs/{uuid}", status_code=303)


# ── RECHECK (delete checksum + re-checksum + re-upload + re-verify)
@router.post("/{uuid}/recheck")
def recheck_run(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/runs/{uuid}/recheck")
    return RedirectResponse(url=f"/runs/{uuid}", status_code=303)


# ── DELETE
@router.post("/{uuid}/delete")
def delete_run(request: Request, uuid: str):
    httpx.delete(f"{BACKEND_URL}/runs/{uuid}")
    return RedirectResponse(url="/runs/", status_code=303)
