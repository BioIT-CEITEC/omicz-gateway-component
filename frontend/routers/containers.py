import docker
import docker.errors
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from routers.settings import get_setting_value

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _client():
    try:
        return docker.from_env()
    except Exception:
        return None


def _fetch_containers():
    client = _client()
    if client is None:
        return None  # None = Docker unreachable (show error banner)
    try:
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            if not c.name.startswith("fastapi_gateway_"):
                continue
            result.append({
                "id":     c.short_id,
                "name":   c.name,
                "status": c.status,
                "image":  c.image.tags[0] if c.image.tags else c.image.short_id,
            })
        result.sort(key=lambda x: x["name"])
        return result
    except Exception:
        return None


@router.get("/")
def containers_page(request: Request):
    containers = _fetch_containers()
    return templates.TemplateResponse(request, "containers/index.html", {
        "containers": containers if containers is not None else [],
        "docker_error": containers is None,
        "refresh_interval": get_setting_value("containers_refresh_interval", 10),
    })


@router.get("/data")
def containers_data():
    containers = _fetch_containers()
    return {
        "containers": containers if containers is not None else [],
        "docker_error": containers is None,
    }


@router.post("/{name}/restart")
def restart_container(name: str, next: str = "/containers/"):
    client = _client()
    if client is not None:
        try:
            container = client.containers.get(name)
            container.restart()
        except Exception:
            pass
    return RedirectResponse(url=next, status_code=303)
