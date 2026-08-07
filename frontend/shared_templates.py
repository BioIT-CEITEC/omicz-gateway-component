import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from lang import LANG

_WORKSPACE_VERSION = "/workspace/VERSION"

# Deployment-wide display timezone — same convention/env var as backend and
# frontend logging (core/logger.py, logger.py) so log timestamps and UI
# timestamps agree.
DISPLAY_TIMEZONE = os.getenv("LOG_TIMEZONE", "Europe/Prague")
_DISPLAY_TZ = ZoneInfo(DISPLAY_TIMEZONE)


def _read_version() -> str:
    try:
        with open(_WORKSPACE_VERSION) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def local_dt(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a UTC ISO timestamp (as stored/returned by the backend) in the
    deployment's local display timezone."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_DISPLAY_TZ).strftime(fmt)


class _DynamicTemplates(Jinja2Templates):
    """Jinja2Templates that injects APP_VERSION and lang on every render."""

    def TemplateResponse(self, *args, **kwargs):
        # Inject current version and UI language dict into context on every request
        if args and isinstance(args[-1], dict):
            args[-1].setdefault("APP_VERSION", _read_version())
            args[-1].setdefault("lang", LANG)
            args[-1].setdefault("DISPLAY_TIMEZONE", DISPLAY_TIMEZONE)
        elif "context" in kwargs:
            kwargs["context"].setdefault("APP_VERSION", _read_version())
            kwargs["context"].setdefault("lang", LANG)
            kwargs["context"].setdefault("DISPLAY_TIMEZONE", DISPLAY_TIMEZONE)
        return super().TemplateResponse(*args, **kwargs)


templates = _DynamicTemplates(directory="templates")
templates.env.filters["local_dt"] = local_dt
