from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class ShowRunDirectory(BaseModel):
    uuid:         UUID
    name:         str
    state:        str
    file_count:   int
    total_bytes:  int
    stable_since: datetime | None = None
    sent_at:      datetime | None = None
    progress:     str | None = None
    detail:       str | None = None

    class Config:
        from_attributes = True
