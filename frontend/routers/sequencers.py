import os
import httpx
from typing import List

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


def fetch_types() -> list:
    """Fetch all sequencer types from the backend — used to populate dropdowns."""
    response = httpx.get(f"{BACKEND_URL}/sequencers-types/")
    return safe_json(response, fallback={}).get("results", [])


# ── LIST 
@router.get("/")
def list_sequencers(request: Request, skip: int = 0, limit: int = 20):
    response = httpx.get(f"{BACKEND_URL}/sequencers/", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    return templates.TemplateResponse(request, "sequencers/list.html", {"data": data})


# ── CREATE — show form 
@router.get("/create")
def create_sequencer_form(request: Request):
    return templates.TemplateResponse(request, "sequencers/create.html", {"types": fetch_types()})


# ── CREATE — handle form submission
@router.post("/create")
def create_sequencer(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    status: str = Form(...),
    type_uuid: str = Form(...),
    sent_to_tre: str = Form(default="manual"),
    exclusions: List[str] = Form(default=[]),
):
    cleaned_exclusions = [e.strip() for e in exclusions if e.strip()]
    payload = {"name": name, "location": location, "status": status, "type_uuid": type_uuid,
               "sent_to_tre": sent_to_tre, "exclusions": cleaned_exclusions}
    response = httpx.post(f"{BACKEND_URL}/sequencers/", json=payload)

    if response.status_code == 201:
        sequencer = safe_json(response, fallback={})
        return RedirectResponse(url=f"/sequencers/{sequencer['uuid']}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    return templates.TemplateResponse(request, "sequencers/create.html", {"error": error, "types": fetch_types()})


# ── DETAIL 
@router.get("/{uuid}")
def detail_sequencer(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/sequencers/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    sequencer = safe_json(response, fallback={})
    return templates.TemplateResponse(request, "sequencers/detail.html", {"sequencer": sequencer})


# ── EDIT — show form ──
@router.get("/{uuid}/edit")
def edit_sequencer_form(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/sequencers/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    sequencer = safe_json(response, fallback={})
    return templates.TemplateResponse(request, "sequencers/edit.html", {"sequencer": sequencer, "types": fetch_types()})


# ── EDIT — handle form submission
@router.post("/{uuid}/edit")
def edit_sequencer(
    request: Request,
    uuid: str,
    name: str = Form(...),
    location: str = Form(...),
    status: str = Form(...),
    type_uuid: str = Form(...),
    sent_to_tre: str = Form(default="manual"),
    exclusions: List[str] = Form(default=[]),
):
    cleaned_exclusions = [e.strip() for e in exclusions if e.strip()]
    payload = {"name": name, "location": location, "status": status, "type_uuid": type_uuid,
               "sent_to_tre": sent_to_tre, "exclusions": cleaned_exclusions}
    response = httpx.patch(f"{BACKEND_URL}/sequencers/{uuid}", json=payload)

    if response.status_code == 200:
        return RedirectResponse(url=f"/sequencers/{uuid}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    sequencer = {"uuid": uuid, "name": name, "location": location, "status": status,
                 "type_uuid": type_uuid, "sent_to_tre": sent_to_tre, "exclusions": cleaned_exclusions}
    return templates.TemplateResponse(request, "sequencers/edit.html", {"sequencer": sequencer, "error": error, "types": fetch_types()})


# ── DELETE 
@router.post("/{uuid}/delete")
def delete_sequencer(request: Request, uuid: str):
    httpx.delete(f"{BACKEND_URL}/sequencers/{uuid}")
    return RedirectResponse(url="/sequencers/", status_code=303)
