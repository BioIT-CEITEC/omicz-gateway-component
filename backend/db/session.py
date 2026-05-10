from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import settings

SQLALEMY_DATABASE_URL = settings.POSTGRES_URL

engine = create_engine(SQLALEMY_DATABASE_URL)
SESSION_LOCAL = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    db = SESSION_LOCAL()
    try:
        yield db
    finally:
        db.close()
