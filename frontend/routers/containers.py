import os
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from routers.settings import get_setting_value

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


def _fetch_containers():
    try:
        res = httpx.get(f"{BACKEND_URL}/containers/", timeout=5)
        if res.status_code == 200:
            return res.json().get("containers", [])
    except Exception:
        pass
    return []


@router.get("/")
def containers_page(request: Request):
    containers = _fetch_containers()
    return templates.TemplateResponse(request, "containers/index.html", {
        "containers": containers,
        "refresh_interval": get_setting_value("containers_refresh_interval", 10),
    })


@router.get("/data")
def containers_data():
    return {"containers": _fetch_containers()}


@router.post("/{name}/restart")
def restart_container(name: str):
    try:
        httpx.post(f"{BACKEND_URL}/containers/{name}/restart", timeout=15)
    except Exception:
        pass
    return RedirectResponse(url="/containers/", status_code=303)
