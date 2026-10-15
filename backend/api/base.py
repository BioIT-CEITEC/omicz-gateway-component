from fastapi import APIRouter, Depends

from api.deps import require_user
from api.v1 import sequnecers
from api.v1 import runs
from api.v1 import sequencers_types
from api.v1 import containers
from api.v1 import settings
from api.v1 import logs
from api.v1 import auth
from api.v1 import users

api_router = APIRouter()
# login, refresh and first-time setup work without a token; everything else needs one
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
logged_in = [Depends(require_user)]
api_router.include_router(users.router, prefix="/users", tags=["users"], dependencies=logged_in)
api_router.include_router(sequnecers.router, prefix="/sequencers", tags=["sequencers"], dependencies=logged_in)
api_router.include_router(runs.router, prefix="/runs", tags=["runs"], dependencies=logged_in)
api_router.include_router(sequencers_types.router, prefix="/sequencers-types", tags=["sequencers-types"], dependencies=logged_in)
api_router.include_router(containers.router, prefix="/containers", tags=["containers"], dependencies=logged_in)
api_router.include_router(settings.router, prefix="/settings", tags=["settings"], dependencies=logged_in)
api_router.include_router(logs.router, prefix="/logs", tags=["logs"], dependencies=logged_in)
