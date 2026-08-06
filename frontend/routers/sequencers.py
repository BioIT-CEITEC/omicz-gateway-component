import os
import httpx
from typing import List

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from routers.settings import get_setting_value

router = APIRouter()
from shared_templates import templates

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
def list_sequencers(request: Request, skip: int = 0, limit: int | None = None):
    if limit is None: limit = get_setting_value("pagination_page_size", 20)
    response = httpx.get(f"{BACKEND_URL}/sequencers/", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    mount_res = httpx.get(f"{BACKEND_URL}/sequencers/mount-status")
    mount_data = safe_json(mount_res, fallback={"mounts": [], "all_accessible": True, "inaccessible_count": 0})
    # Build a lookup: uuid → accessible bool for use in the template
    mount_map = {m["uuid"]: m["accessible"] for m in mount_data.get("mounts", [])}
    return templates.TemplateResponse(request, "sequencers/list.html", {
        "data": data,
        "mount_map": mount_map,
        "mount_warnings": [m for m in mount_data.get("mounts", []) if not m["accessible"]],
    })


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
        return RedirectResponse(url=f"/instruments/{sequencer['uuid']}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    return templates.TemplateResponse(request, "sequencers/create.html", {"error": error, "types": fetch_types()})


# ── DETAIL
@router.get("/{uuid}")
def detail_sequencer(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/sequencers/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    sequencer = safe_json(response, fallback={})
    type_name = None
    if sequencer.get("type_uuid"):
        type_res = httpx.get(f"{BACKEND_URL}/sequencers-types/{sequencer['type_uuid']}")
        if type_res.status_code == 200:
            type_name = safe_json(type_res, fallback={}).get("name")
    return templates.TemplateResponse(request, "sequencers/detail.html", {"sequencer": sequencer, "type_name": type_name})


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
        return RedirectResponse(url=f"/instruments/{uuid}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    sequencer = {"uuid": uuid, "name": name, "location": location, "status": status,
                 "type_uuid": type_uuid, "sent_to_tre": sent_to_tre, "exclusions": cleaned_exclusions}
    return templates.TemplateResponse(request, "sequencers/edit.html", {"sequencer": sequencer, "error": error, "types": fetch_types()})


# ── TOGGLE STATUS
@router.post("/{uuid}/toggle-status")
def toggle_sequencer_status(request: Request, uuid: str):
    httpx.post(f"{BACKEND_URL}/sequencers/{uuid}/toggle-status")
    return RedirectResponse(url="/instruments/", status_code=303)


# ── DELETE
@router.post("/{uuid}/delete")
def delete_sequencer(request: Request, uuid: str):
    httpx.delete(f"{BACKEND_URL}/sequencers/{uuid}")
    return RedirectResponse(url="/instruments/", status_code=303)
