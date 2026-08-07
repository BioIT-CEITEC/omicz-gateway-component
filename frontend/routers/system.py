import os
import subprocess
import threading
import time

import docker
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from logger import get_logger

router = APIRouter()
logger = get_logger("frontend")

WORKSPACE = "/workspace"
# GitHub API returns the file directly with proper cache headers — more reliable than raw CDN
GITHUB_API_VERSION = "https://api.github.com/repos/BioIT-CEITEC/omicz-gateway-component/contents/VERSION"
_VERSION_CACHE_TTL = 10  # cache GitHub result server-side for 10 seconds

_RESTART_ORDER = [
    "fastapi_gateway_watcher",
    "fastapi_gateway_worker",
    "fastapi_gateway_backend",
    "fastapi_gateway_frontend",
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
        r = httpx.get(
            GITHUB_API_VERSION,
            headers={"Accept": "application/vnd.github.v3.raw"},
            timeout=5,
        )
        if r.status_code == 200:
            _cached_latest = r.text.strip()
            _cache_fetched_at = time.time()
            return _cached_latest
    except Exception:
        pass
    return None


def _invalidate_version_cache() -> None:
    global _cached_latest, _cache_fetched_at
    _cached_latest = None
    _cache_fetched_at = 0.0


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
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", WORKSPACE],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "config", "--global", "url.https://github.com/.insteadOf", "git@github.com:"],
            capture_output=True, timeout=10,
        )
        result = subprocess.run(
            ["git", "-C", WORKSPACE, "pull", "--ff-only"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        git_output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return JSONResponse({"success": False, "error": git_output}, status_code=500)
    except FileNotFoundError:
        return JSONResponse(
            {
                "success": False,
                "error": (
                    "git is not installed in this container.\n"
                    "The frontend image needs to be rebuilt with the latest Dockerfile.\n\n"
                    "On the server, run:\n"
                    "  docker compose build frontend\n"
                    "  docker compose up -d frontend"
                ),
            },
            status_code=500,
        )
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    logger.info(f"git pull completed: {git_output}")
    _invalidate_version_cache()

    needs_rebuild   = any(k in result.stdout for k in ["requirements.txt", "Dockerfile"])
    needs_migration = "alembic/versions" in result.stdout

    # ── Step 2: run migrations if needed ─────────────────────────────────────
    migration_log = []
    if needs_migration:
        try:
            client = docker.from_env()
            backend = client.containers.get("fastapi_gateway_backend")
            exit_code, output = backend.exec_run(
                ["alembic", "upgrade", "head"],
                workdir="/app",
            )
            migration_output = output.decode("utf-8", errors="replace").strip()
            if exit_code == 0:
                migration_log.append("migrations applied successfully")
                logger.info(f"alembic upgrade head: {migration_output}")
            else:
                migration_log.append(f"migration failed (exit {exit_code}): {migration_output}")
                logger.error(f"alembic upgrade head failed: {migration_output}")
        except Exception as e:
            migration_log.append(f"could not run migrations: {e}")
            logger.error(f"migration error: {e}")

    # ── Step 3: restart services via Docker SDK ───────────────────────────────
    # Frontend is restarted last in a background thread with a delay so the
    # response reaches the browser before the container shuts down.
    #
    # NOTE: this only restarts containers that already exist, on their current
    # (already-built) image. It does NOT rebuild images or create containers
    # for services newly added to docker-compose.yml. When a change touches
    # a Dockerfile/requirements.txt or adds a new service, an admin must also
    # run `docker compose up -d --build` from the host once, manually.
    restart_log = []
    frontend_name = "fastapi_gateway_frontend"
    try:
        client = docker.from_env()
        for name in _RESTART_ORDER:
            if name == frontend_name:
                continue  # handled below
            try:
                client.containers.get(name).restart()
                restart_log.append(f"restarted {name}")
                logger.info(f"restarted {name}")
            except Exception as e:
                restart_log.append(f"could not restart {name}: {e}")
                logger.warning(f"could not restart {name}: {e}")
    except Exception as e:
        restart_log.append(f"Docker SDK error: {e}")
        logger.error(f"Docker SDK error during update: {e}")

    # Schedule frontend restart after a 3-second delay so response is delivered first
    def _restart_frontend():
        time.sleep(3)
        try:
            docker.from_env().containers.get(frontend_name).restart()
            logger.info(f"restarted {frontend_name}")
        except Exception as e:
            logger.warning(f"could not restart {frontend_name}: {e}")

    threading.Thread(target=_restart_frontend, daemon=True).start()
    restart_log.append(f"restarting {frontend_name} in 3 s…")

    return JSONResponse({
        "success": True,
        "git_output": git_output,
        "migration_log": migration_log,
        "restart_log": restart_log,
        "needs_rebuild": needs_rebuild,
        "needs_migration": needs_migration,
    })
