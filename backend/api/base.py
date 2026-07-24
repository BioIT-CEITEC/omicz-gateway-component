from fastapi import APIRouter
from api.v1 import sequnecers
from api.v1 import runs
from api.v1 import sequencers_types
from api.v1 import containers
from api.v1 import settings
from api.v1 import logs

api_router = APIRouter()
api_router.include_router(sequnecers.router, prefix="/sequencers", tags=["sequencers"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(sequencers_types.router, prefix="/sequencers-types", tags=["sequencers-types"])
api_router.include_router(containers.router, prefix="/containers", tags=["containers"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])

