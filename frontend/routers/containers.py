import docker
import docker.errors
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from routers.settings import get_setting_value

router = APIRouter()
from shared_templates import templates

# Containers to recreate on remount-restart (order matters: stop reverse, start forward)
_REMOUNT_CONTAINERS = [
    "fastapi_gateway_backend",
    "fastapi_gateway_worker",
    "fastapi_gateway_watcher",
]


def _client():
    try:
        return docker.from_env()
    except Exception:
        return None


def _fetch_containers():
    client = _client()
    if client is None:
        return None
    try:
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            if not c.name.startswith("fastapi_gateway_"):
                continue
            try:
                image = c.image.tags[0] if c.image.tags else c.image.short_id
            except docker.errors.ImageNotFound:
                image = c.attrs["Config"]["Image"]
            result.append({
                "id":     c.short_id,
                "name":   c.name,
                "status": c.status,
                "image":  image,
            })
        result.sort(key=lambda x: x["name"])
        return result
    except Exception:
        return None


def _force_recreate(client, name: str):
    """Stop, remove, and recreate a container with its existing config.
    This re-establishes VirtioFS volume bindings on Docker Desktop (macOS/Windows).
    """
    c = client.containers.get(name)

    # Snapshot full config before stopping
    image         = c.attrs["Config"]["Image"]
    cmd           = c.attrs["Config"].get("Cmd")
    env           = c.attrs["Config"].get("Env") or []
    labels        = c.attrs["Config"].get("Labels") or {}
    binds         = c.attrs["HostConfig"].get("Binds") or []
    port_bindings = c.attrs["HostConfig"].get("PortBindings") or {}
    restart_pol   = c.attrs["HostConfig"].get("RestartPolicy") or {}
    networks      = dict(c.attrs["NetworkSettings"]["Networks"])

    c.stop(timeout=30)
    c.remove()

    host_config = client.api.create_host_config(
        binds=binds,
        port_bindings=port_bindings or None,
        restart_policy=restart_pol if restart_pol.get("Name") else {"Name": "always"},
    )

    container_id = client.api.create_container(
        image=image,
        name=name,
        command=cmd,
        environment=env,
        labels=labels,
        host_config=host_config,
    )["Id"]

    # Re-connect to the same networks, preserving service-name aliases.
    # Filter out 12-char hex container IDs (old container's short ID) — keep only
    # human-readable aliases like "backend", "worker", "watcher".
    for net_name, net_info in networks.items():
        if net_name == "bridge":
            continue
        try:
            import re
            all_aliases = net_info.get("Aliases") or []
            aliases = [a for a in all_aliases if not re.fullmatch(r"[0-9a-f]{12}", a)]
            client.networks.get(net_name).connect(container_id, aliases=aliases or None)
        except Exception:
            pass

    client.api.start(container_id)


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


@router.post("/remount-restart")
def remount_restart(next: str = "/"):
    """Force-recreate backend, worker and watcher to re-establish storage mounts."""
    client = _client()
    if client is None:
        return RedirectResponse(url=next, status_code=303)

    # Stop in reverse order first
    for name in reversed(_REMOUNT_CONTAINERS):
        try:
            client.containers.get(name).stop(timeout=30)
        except Exception:
            pass

    # Recreate in forward order
    for name in _REMOUNT_CONTAINERS:
        try:
            _force_recreate(client, name)
        except Exception:
            pass

    return RedirectResponse(url=next, status_code=303)


@router.post("/restart-all")
def restart_all(next: str = "/containers/"):
    """Force-recreate all fastapi_gateway_* containers except the frontend itself.
    Infrastructure (rabbitmq) is stopped last and recreated first so dependents start in order.
    """
    client = _client()
    if client is None:
        return RedirectResponse(url=next, status_code=303)

    all_names = [
        c.name for c in client.containers.list(all=True)
        if c.name.startswith("fastapi_gateway_") and c.name != "fastapi_gateway_frontend"
    ]

    # Infra services (message broker etc.) — stop last, recreate first
    INFRA = {"fastapi_gateway_rabbitmq"}
    infra   = [n for n in all_names if n in INFRA]
    apps    = [n for n in all_names if n not in INFRA]

    # Stop apps first, then infra
    for name in apps + infra:
        try:
            client.containers.get(name).stop(timeout=30)
        except Exception:
            pass

    # Recreate infra first, then apps
    for name in infra + apps:
        try:
            _force_recreate(client, name)
        except Exception:
            pass

    return RedirectResponse(url=next, status_code=303)


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
