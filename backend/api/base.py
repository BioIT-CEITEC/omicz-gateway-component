from fastapi import APIRouter
from api.v1 import users
from api.v1 import sequnecers
from api.v1 import runs
from api.v1 import sequencers_types
from api.v1 import k8s_proxy

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(sequnecers.router, prefix="/sequencers", tags=["sequencers"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(sequencers_types.router, prefix="/sequencers-types", tags=["sequencers-types"])
api_router.include_router(k8s_proxy.router, prefix="/k8s-proxy", tags=["k8s-proxy"])

