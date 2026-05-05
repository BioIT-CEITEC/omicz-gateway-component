from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from core.config import settings
from core.logger import get_logger
from api.base import api_router
import db.base  # ensures all models are registered before any mapper is used

logger = get_logger("backend")

def include_router(app: FastAPI):
    app.include_router(api_router)

def start_app():
    app = FastAPI(title=settings.PROJECT_TITLE, version=settings.PROJECT_VERSION, description=settings.PROJECT_DESCRIPTION)
    include_router(app)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"unhandled error: {request.method} {request.url} — {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    return app

app = start_app()
