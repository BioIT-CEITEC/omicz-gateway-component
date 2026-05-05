import os
import httpx
from fastapi import APIRouter, Request, Form
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


# ── LIST ──
@router.get("/")
def list_sequencer_types(request: Request, skip: int = 0, limit: int = 20):
    response = httpx.get(f"{BACKEND_URL}/sequencers-types/", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    return templates.TemplateResponse(request, "sequencers-types/list.html", {"data": data})


# ── CREATE — show form 
@router.get("/create")
def create_sequencer_type_form(request: Request):
    return templates.TemplateResponse(request, "sequencers-types/create.html")


# ── CREATE — handle form submission 
@router.post("/create")
def create_sequencer_type(
    request: Request,
    name: str = Form(...),
    completion_signal: str = Form(...),
    signal_match: str = Form(...),
):
    payload = {"name": name, "completion_signal": completion_signal, "signal_match": signal_match}
    response = httpx.post(f"{BACKEND_URL}/sequencers-types/", json=payload)

    if response.status_code == 201:
        st = safe_json(response, fallback={})
        return RedirectResponse(url=f"/sequencers-types/{st['uuid']}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    return templates.TemplateResponse(request, "sequencers-types/create.html", {"error": error})


# ── DETAIL 
@router.get("/{uuid}")
def detail_sequencer_type(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/sequencers-types/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    st = safe_json(response, fallback={})
    return templates.TemplateResponse(request, "sequencers-types/detail.html", {"st": st})


# ── EDIT — show form ──
@router.get("/{uuid}/edit")
def edit_sequencer_type_form(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/sequencers-types/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    st = safe_json(response, fallback={})
    return templates.TemplateResponse(request, "sequencers-types/edit.html", {"st": st})


# ── EDIT — handle form submission 
@router.post("/{uuid}/edit")
def edit_sequencer_type(
    request: Request,
    uuid: str,
    name: str = Form(...),
    completion_signal: str = Form(...),
    signal_match: str = Form(...),
):
    payload = {"name": name, "completion_signal": completion_signal, "signal_match": signal_match}
    response = httpx.patch(f"{BACKEND_URL}/sequencers-types/{uuid}", json=payload)

    if response.status_code == 200:
        return RedirectResponse(url=f"/sequencers-types/{uuid}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    st = {"uuid": uuid, "name": name, "completion_signal": completion_signal, "signal_match": signal_match}
    return templates.TemplateResponse(request, "sequencers-types/edit.html", {"st": st, "error": error})


# ── DELETE 
@router.post("/{uuid}/delete")
def delete_sequencer_type(request: Request, uuid: str):
    httpx.delete(f"{BACKEND_URL}/sequencers-types/{uuid}")
    return RedirectResponse(url="/sequencers-types/", status_code=303)
