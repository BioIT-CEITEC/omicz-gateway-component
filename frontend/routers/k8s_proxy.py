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


@router.get("/")
def k8s_proxy_page(request: Request):
    status_res = httpx.get(f"{BACKEND_URL}/k8s-proxy/status")
    status     = safe_json(status_res, fallback={"status": "unknown", "pid": None})

    config_res = httpx.get(f"{BACKEND_URL}/k8s-proxy/config")
    config     = safe_json(config_res, fallback=None) if config_res.status_code == 200 else None

    return templates.TemplateResponse(request, "k8s_proxy/index.html", {
        "status": status,
        "config": config,
    })


@router.post("/save-config")
def save_config(
    request:      Request,
    namespace:    str = Form(...),
    service_name: str = Form(...),
    local_port:   int = Form(8080),
    remote_port:  int = Form(8080),
    kubeconfig:   str = Form(...),
):
    httpx.post(f"{BACKEND_URL}/k8s-proxy/config", json={
        "namespace":    namespace,
        "service_name": service_name,
        "local_port":   local_port,
        "remote_port":  remote_port,
        "kubeconfig":   kubeconfig,
    })
    return RedirectResponse(url="/k8s-proxy/", status_code=303)


@router.post("/start")
def start_proxy(request: Request):
    httpx.post(f"{BACKEND_URL}/k8s-proxy/start")
    return RedirectResponse(url="/k8s-proxy/", status_code=303)


@router.post("/stop")
def stop_proxy(request: Request):
    httpx.post(f"{BACKEND_URL}/k8s-proxy/stop")
    return RedirectResponse(url="/k8s-proxy/", status_code=303)


# ── JSON endpoints polled by JS ───────────────────────────────────────────────

@router.get("/status-data")
def status_data():
    res = httpx.get(f"{BACKEND_URL}/k8s-proxy/status")
    return safe_json(res, fallback={"status": "unknown", "pid": None})


@router.get("/logs-data")
def logs_data():
    res = httpx.get(f"{BACKEND_URL}/k8s-proxy/logs")
    return safe_json(res, fallback={"logs": []})
