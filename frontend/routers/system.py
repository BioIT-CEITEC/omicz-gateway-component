import os
import subprocess
import threading
import time

import docker
import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

import updater
from logger import get_logger

router = APIRouter()
logger = get_logger("frontend")

WORKSPACE   = "/workspace"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
# GitHub API returns the file directly with proper cache headers — more reliable than raw CDN
GITHUB_API_VERSION = "https://api.github.com/repos/BioIT-CEITEC/omicz-gateway-component/contents/VERSION"
# Every page load asks for the latest version. Unauthenticated GitHub API calls are
# limited to 60/hour per IP, so cache for 15 min; the Settings "Check" button forces a refresh.
_VERSION_CACHE_TTL = 15 * 60

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
def get_version(refresh: bool = Query(False)):
    if refresh:
        _invalidate_version_cache()
    current = read_current_version()
    latest = fetch_latest_version()
    return {
        "current": current,
        "latest": latest,
        "update_available": latest is not None and latest != current,
        "workspace_mounted": os.path.isdir(WORKSPACE),
    }


def _active_transfers() -> dict | None:
    """Transfers a worker restart would interrupt, from the backend. None if the backend can't be asked."""
    try:
        r = httpx.get(f"{BACKEND_URL}/runs/active-transfers", timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _run_migrations() -> tuple[bool, str]:
    """Always run `alembic upgrade head` — it is a no-op when the database is already current."""
    try:
        backend = docker.from_env().containers.get("fastapi_gateway_backend")
        exit_code, output = backend.exec_run(["alembic", "upgrade", "head"], workdir="/app")
        text = output.decode("utf-8", errors="replace").strip()
        return exit_code == 0, text
    except Exception as e:
        return False, str(e)


@router.post("/update")
def do_update(force: bool = Query(False)):
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

    # ── Step 0: don't interrupt transfers without asking ─────────────────────
    # Restarting the worker marks a running checksum/upload as failed (Retry resumes it).
    if not force:
        active = _active_transfers()
        if active and active.get("count"):
            names = [f"{r['name']} ({r['status']})" for r in active.get("runs", [])] + active.get("directories", [])
            return JSONResponse(
                {
                    "success": False,
                    "busy": True,
                    "error": (
                        f"{active['count']} transfer(s) in progress: " + ", ".join(names[:10])
                        + ("…" if len(names) > 10 else "")
                        + ".\nUpdating restarts the worker and interrupts them (they can be resumed with Retry). "
                        "Wait until they finish, or update anyway."
                    ),
                },
                status_code=409,
            )

    # ── Step 1: git pull, keeping local edits ─────────────────────────────────
    try:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", WORKSPACE],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "config", "--global", "url.https://github.com/.insteadOf", "git@github.com:"],
            capture_output=True, timeout=10,
        )
        pull = updater.pull_keeping_local_changes(WORKSPACE)
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

    if not pull["ok"]:
        logger.warning(f"update aborted: {pull['error']}")
        return JSONResponse({"success": False, "error": pull["error"], "local_changes_log": pull.get("log", [])},
                            status_code=500)

    git_output = pull["output"]
    changed    = pull["changed_files"]
    logger.info(f"git pull completed: {git_output}")
    _invalidate_version_cache()

    if not changed:
        return JSONResponse({
            "success": True, "git_output": git_output or "Already up to date.",
            "local_changes_log": pull["log"], "migration_log": [], "restart_log": [], "warnings": [],
            "needs_rebuild": False, "needs_compose_up": False,
        })

    needs_rebuild    = any(f.endswith(("requirements.txt", "Dockerfile")) for f in changed)
    needs_compose_up = any(os.path.basename(f) == "docker-compose.yml" for f in changed)

    # ── Step 2: migrations — always, right after the pull, before any restart ──
    # The backend reloads on the new files by itself, so run this as early as possible.
    migrated, migration_output = _run_migrations()
    migration_log = [migration_output or "database already up to date"]
    warnings = []
    if migrated:
        logger.info(f"alembic upgrade head: {migration_output}")
    else:
        logger.error(f"alembic upgrade head failed: {migration_output}")
        warnings.append(
            "Database migration FAILED — the worker and watcher were NOT restarted and keep running the previous "
            "version. Check the backend logs, then run on the server: "
            "docker exec fastapi_gateway_backend alembic upgrade head"
        )

    # ── Step 3: restart services via Docker SDK ───────────────────────────────
    # Frontend is restarted last in a background thread with a delay so the
    # response reaches the browser before the container shuts down.
    #
    # NOTE: this only restarts containers that already exist, on their current
    # (already-built) image. It does NOT rebuild images or apply docker-compose.yml
    # changes; those need `docker compose up -d --build` on the host (reported below).
    restart_log = []
    frontend_name = "fastapi_gateway_frontend"
    restart = [n for n in _RESTART_ORDER if n != frontend_name]
    if not migrated:
        restart = []  # new code on an old schema would fail — keep the previous version running
    try:
        client = docker.from_env()
        for name in restart:
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

    if needs_compose_up:
        warnings.append("docker-compose.yml changed — to apply it, run on the server: docker compose up -d")

    return JSONResponse({
        "success": True,
        "git_output": git_output,
        "local_changes_log": pull["log"],
        "migration_log": migration_log,
        "restart_log": restart_log,
        "warnings": warnings,
        "needs_rebuild": needs_rebuild,
        "needs_compose_up": needs_compose_up,
        "needs_migration": True,
    })
