import os
import subprocess
import time

import docker
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from logger import get_logger

router = APIRouter()
logger = get_logger("frontend")

WORKSPACE = "/workspace"
GITHUB_RAW_VERSION = "https://raw.githubusercontent.com/BioIT-CEITEC/omicz-gateway-component/main/VERSION"
_VERSION_CACHE_TTL = 300  # seconds — hit GitHub at most once every 5 minutes

# Services to restart after a git pull (frontend restarts itself last via Docker SDK)
_RESTART_ORDER = [
    "fastapi_gateway_watcher",
    "fastapi_gateway_worker",
    "fastapi_gateway_backend",
]

_cached_latest: str | None = None
_cache_fetched_at: float = 0.0


def read_current_version() -> str:
    try:
        with open(os.path.join(WORKSPACE, "VERSION")) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def fetch_latest_version() -> str | None:
    global _cached_latest, _cache_fetched_at
    if _cached_latest is not None and time.time() - _cache_fetched_at < _VERSION_CACHE_TTL:
        return _cached_latest
    try:
        url = f"{GITHUB_RAW_VERSION}?t={int(time.time())}"
        r = httpx.get(url, headers={"Cache-Control": "no-cache"}, timeout=5)
        if r.status_code == 200:
            _cached_latest = r.text.strip()
            _cache_fetched_at = time.time()
            return _cached_latest
    except Exception:
        pass
    return None


@router.get("/version")
def get_version():
    current = read_current_version()
    latest = fetch_latest_version()
    return {
        "current": current,
        "latest": latest,
        "update_available": latest is not None and latest != current,
        "workspace_mounted": os.path.isdir(WORKSPACE),
    }


@router.post("/update")
def do_update():
    if not os.path.isdir(WORKSPACE):
        return JSONResponse(
            {
                "success": False,
                "error": (
                    "Workspace not mounted. "
                    "Add '- .:/workspace' to the frontend service volumes in docker-compose.yml and recreate the container."
                ),
            },
            status_code=400,
        )

    # ── Step 1: git pull ──────────────────────────────────────────────────────
    try:
        # Avoid "dubious ownership" error when repo root is owned by host user
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", WORKSPACE],
            capture_output=True,
            timeout=10,
        )
        # Rewrite SSH remote URLs to HTTPS so git pull works without an SSH client
        subprocess.run(
            ["git", "config", "--global", "url.https://github.com/.insteadOf", "git@github.com:"],
            capture_output=True,
            timeout=10,
        )
        result = subprocess.run(
            ["git", "-C", WORKSPACE, "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        git_output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return JSONResponse({"success": False, "error": git_output}, status_code=500)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    logger.info(f"git pull completed: {git_output}")

    # Detect if a Docker rebuild or migration is needed
    needs_rebuild  = any(k in result.stdout for k in ["requirements.txt", "Dockerfile"])
    needs_migration = "alembic/versions" in result.stdout

    # ── Step 2: restart backend / worker / watcher via Docker SDK ─────────────
    restart_log = []
    try:
        client = docker.from_env()
        for name in _RESTART_ORDER:
            try:
                c = client.containers.get(name)
                c.restart()
                restart_log.append(f"restarted {name}")
                logger.info(f"restarted {name}")
            except Exception as e:
                restart_log.append(f"could not restart {name}: {e}")
                logger.warning(f"could not restart {name}: {e}")
    except Exception as e:
        restart_log.append(f"Docker SDK error: {e}")
        logger.error(f"Docker SDK error during update: {e}")

    return JSONResponse(
        {
            "success": True,
            "git_output": git_output,
            "restart_log": restart_log,
            "needs_rebuild": needs_rebuild,
            "needs_migration": needs_migration,
        }
    )
