from datetime import datetime
from typing import Literal
from uuid import UUID
import re
from pydantic import BaseModel, Field, model_validator

def generate_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug

class SequencerCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=100, examples=["My Sequencer"])
    slug: str | None = Field(default=None, examples=["my-sequencer"])
    location: str = Field(..., examples=["Studio A"])
    author_id:  int | None  = None
    type_uuid:  UUID | None = None
    status: str = Field(default="active", examples=["active"])
    sent_to_tre: Literal["auto", "manual"] = "manual"
    exclusions: list[str] = []

    @model_validator(mode="after")
    def set_slug(self) -> "SequencerCreate":
        if not self.slug:
            self.slug = generate_slug(self.name)
        return self


class SequencerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=100, examples=["My Sequencer"])
    slug: str | None = Field(default=None, examples=["my-sequencer"])
    location: str | None = Field(default=None, examples=["Studio A"])
    author_id:  int | None  = None
    type_uuid:  UUID | None = None
    status: str | None = Field(default=None, examples=["active"])
    sent_to_tre: Literal["auto", "manual"] | None = None
    exclusions: list[str] | None = None

    @model_validator(mode="after")
    def regenerate_slug(self) -> "SequencerUpdate":
        if self.name and not self.slug:
            self.slug = generate_slug(self.name)
        return self


class ShowSequencer(BaseModel):
    id: int
    uuid: UUID
    name: str
    slug: str
    location: str
    author_id:  int | None
    type_uuid:  UUID | None
    status: str
    sent_to_tre: str
    exclusions: list[str] | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
