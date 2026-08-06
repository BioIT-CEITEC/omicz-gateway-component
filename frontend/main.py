from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from shared_templates import templates

from routers import home, sequencers, test, sequencers_type, runs, containers, settings, logs, changelog, system
from logger import get_logger

logger = get_logger("frontend")

app = FastAPI(title="Sequencer Gateway UI")

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"unhandled error: {request.method} {request.url} — {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})

# Mount static files (CSS, JS, images)
# static/css/style.css → http://localhost:8001/static/css/style.css
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(home.router)

app.include_router(sequencers.router, prefix="/instruments")
app.include_router(sequencers_type.router, prefix="/instrument-models")
app.include_router(runs.router, prefix="/acquisition-runs")
app.include_router(containers.router, prefix="/containers")
app.include_router(settings.router, prefix="/settings")
app.include_router(logs.router, prefix="/logs")
app.include_router(changelog.router, prefix="/changelog")
app.include_router(system.router, prefix="/system")
app.include_router(test.router, prefix="/test")

