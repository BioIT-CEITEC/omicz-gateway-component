import os
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


def _fetch_settings() -> dict:
    """
    Fetch all settings from backend and return as {key: setting_dict}.
    Falls back to empty dict on error.
    """
    try:
        res = httpx.get(f"{BACKEND_URL}/settings/", timeout=5)
        if res.status_code == 200:
            return {s["key"]: s for s in res.json()}
    except Exception:
        pass
    return {}


def get_setting_value(key: str, default: int) -> int:
    """Fetch a single setting value as int for use in page renders."""
    try:
        res = httpx.get(f"{BACKEND_URL}/settings/{key}", timeout=3)
        if res.status_code == 200:
            return int(res.json()["value"])
    except Exception:
        pass
    return default


@router.get("/")
def settings_page(request: Request):
    settings = _fetch_settings()
    return templates.TemplateResponse(request, "settings/index.html", {"settings": settings})


class SettingValue(BaseModel):
    value: str


@router.put("/update/{key}")
def update_setting(key: str, body: SettingValue):
    try:
        res = httpx.put(f"{BACKEND_URL}/settings/{key}", json={"value": body.value}, timeout=5)
        return JSONResponse(status_code=res.status_code, content=res.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
