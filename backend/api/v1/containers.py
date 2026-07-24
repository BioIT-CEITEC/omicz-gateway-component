import docker
import docker.errors
from fastapi import APIRouter, HTTPException

from core.logger import get_logger

logger = get_logger("backend")
router = APIRouter()


def _client():
    try:
        return docker.from_env()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to Docker socket: {e}")


@router.get("/")
def list_containers():
    client = _client()
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
    return {"containers": result}


@router.post("/{name}/restart")
def restart_container(name: str):
    client = _client()
    try:
        container = client.containers.get(name)
        container.restart()
        logger.info(f"restarted container: {name}")
        return {"detail": f"container '{name}' restarted"}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"container '{name}' not found")
    except Exception as e:
        logger.error(f"failed to restart '{name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))
