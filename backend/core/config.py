import os
from dotenv import load_dotenv

from pathlib import Path
# Load environment variables from .env file
env_path = Path('.') / ".env"
load_dotenv(dotenv_path=env_path)

class Settings:
    API_V1_STR: str = "/api/v1"
    PROJECT_TITLE: str = "GateWay API"
    PROJECT_VERSION: str = "1.3.0"
    PROJECT_DESCRIPTION: str = "API Gateway for sequencer"

    LOG_LEVEL: str    = os.getenv("LOG_LEVEL", "DEBUG").upper()
    LOG_TIMEZONE: str = os.getenv("LOG_TIMEZONE", "Europe/Prague")

    PAGINATION_DEFAULT_SKIP: int  = int(os.getenv("PAGINATION_DEFAULT_SKIP", 0))
    PAGINATION_DEFAULT_LIMIT: int = int(os.getenv("PAGINATION_DEFAULT_LIMIT", 20))
    PAGINATION_MAX_LIMIT: int     = int(os.getenv("PAGINATION_MAX_LIMIT", 200))

    POSTGRES_USERNAME: str = os.getenv("POSTGRES_USERNAME", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "fastapi_gateway_db")
    POSTGRES_URL: str = f"postgresql+psycopg2://{POSTGRES_USERNAME}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

settings = Settings()