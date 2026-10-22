import os
import time

import httpx
from fastapi import APIRouter, Query

router = APIRouter()

WORKSPACE = "/workspace"
# GitHub API returns the file directly with proper cache headers — more reliable than raw CDN
GITHUB_API_VERSION = "https://api.github.com/repos/BioIT-CEITEC/omicz-gateway-component/contents/VERSION"
# Every page load asks for the latest version. Unauthenticated GitHub API calls are
# limited to 60/hour per IP, so cache for 15 min; the Settings "Check" button forces a refresh.
_VERSION_CACHE_TTL = 15 * 60

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
