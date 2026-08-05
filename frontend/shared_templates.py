import os

from fastapi.templating import Jinja2Templates

_WORKSPACE_VERSION = "/workspace/VERSION"


def _read_version() -> str:
    try:
        with open(_WORKSPACE_VERSION) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


class _DynamicTemplates(Jinja2Templates):
    """Jinja2Templates that injects a fresh APP_VERSION on every render."""

    def TemplateResponse(self, *args, **kwargs):
        # Inject current version into context on every request
        if args and isinstance(args[-1], dict):
            args[-1].setdefault("APP_VERSION", _read_version())
        elif "context" in kwargs:
            kwargs["context"].setdefault("APP_VERSION", _read_version())
        return super().TemplateResponse(*args, **kwargs)


templates = _DynamicTemplates(directory="templates")
