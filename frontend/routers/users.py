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


# ── LIST 
@router.get("/")
def list_users(request: Request, skip: int = 0, limit: int = 20):
    response = httpx.get(f"{BACKEND_URL}/users/", params={"skip": skip, "limit": limit})
    data = safe_json(response, fallback={"total": 0, "skip": skip, "limit": limit, "results": []})
    return templates.TemplateResponse(request, "users/list.html", {"data": data})


# ── CREATE — show form 
@router.get("/create")
def create_user_form(request: Request):
    return templates.TemplateResponse(request, "users/create.html")


# ── CREATE — handle form submission
@router.post("/create")
def create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    payload = {"username": username, "email": email, "password": password}
    response = httpx.post(f"{BACKEND_URL}/users/", json=payload)

    if response.status_code == 201:
        user = safe_json(response, fallback={})
        return RedirectResponse(url=f"/users/{user['uuid']}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    return templates.TemplateResponse(request, "users/create.html", {"error": error})


# ── DETAIL 
@router.get("/{uuid}")
def detail_user(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/users/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    user = safe_json(response, fallback={})
    return templates.TemplateResponse(request, "users/detail.html", {"user": user})


# ── EDIT — show form 
@router.get("/{uuid}/edit")
def edit_user_form(request: Request, uuid: str):
    response = httpx.get(f"{BACKEND_URL}/users/{uuid}")
    if response.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    user = safe_json(response, fallback={})
    return templates.TemplateResponse(request, "users/edit.html", {"user": user})


# ── EDIT — handle form submission 
@router.post("/{uuid}/edit")
def edit_user(
    request: Request,
    uuid: str,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
):
    payload = {"username": username, "email": email}
    if password:
        payload["password"] = password
    response = httpx.patch(f"{BACKEND_URL}/users/{uuid}", json=payload)

    if response.status_code == 200:
        return RedirectResponse(url=f"/users/{uuid}", status_code=303)

    error = safe_json(response, fallback={}).get("detail", "Something went wrong")
    user = {"uuid": uuid, "username": username, "email": email}
    return templates.TemplateResponse(request, "users/edit.html", {"user": user, "error": error})


# ── DELETE 
@router.post("/{uuid}/delete")
def delete_user(request: Request, uuid: str):
    httpx.delete(f"{BACKEND_URL}/users/{uuid}")
    return RedirectResponse(url="/users/", status_code=303)
