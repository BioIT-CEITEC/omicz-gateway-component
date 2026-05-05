from uuid import UUID
from pydantic import BaseModel
from typing import Literal


class SequencerTypeCreate(BaseModel):
    name:               str
    completion_signal:  str
    signal_match:       Literal["exact", "prefix", "suffix"] = "exact"


class SequencerTypeUpdate(BaseModel):
    name:               str | None = None
    completion_signal:  str | None = None
    signal_match:       Literal["exact", "prefix", "suffix"] | None = None


class ShowSequencerType(BaseModel):
    id:                 int
    uuid:               UUID
    name:               str
    completion_signal:  str
    signal_match:       str

    class Config:
        from_attributes = True
