from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class ShowRunsStatusHistory(BaseModel):
    uuid:       UUID
    status:     str
    detail:     str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
