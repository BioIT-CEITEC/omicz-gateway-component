from datetime import datetime
from pydantic import BaseModel


class ShowSetting(BaseModel):
    key: str
    value: str
    description: str
    category: str
    updated_at: datetime | None

    class Config:
        from_attributes = True


class UpdateSetting(BaseModel):
    value: str
