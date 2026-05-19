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
    return templates.TemplateResponse(request, "runs/detail.html", {"run": run, "history": history})


# ── START UPLOAD (manual trigger for sent_to_tre=manual)
@router.post("/{uuid}/start-upload")
def start_upload(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/runs/{uuid}/start-upload")
    return RedirectResponse(url=f"/runs/{uuid}", status_code=303)


# ── DELETE
@router.post("/{uuid}/delete")
def delete_run(request: Request, uuid: str):
    httpx.delete(f"{BACKEND_URL}/runs/{uuid}")
    return RedirectResponse(url="/runs/", status_code=303)
