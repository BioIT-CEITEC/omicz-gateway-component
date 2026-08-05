from fastapi.templating import Jinja2Templates

# Single shared Jinja2Templates instance used by all routers.
# main.py sets APP_VERSION on this env at startup.
templates = Jinja2Templates(directory="templates")
