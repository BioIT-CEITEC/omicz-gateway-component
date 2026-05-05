from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, AliasPath


class ShowRun(BaseModel):
    id:             int
    uuid:           UUID
    name:           str
    sequencer_uuid: UUID
    sequencer_name: str | None = Field(default=None, validation_alias=AliasPath('sequencer', 'name'))
    sequencer_sent_to_tre: str | None = Field(default=None, validation_alias=AliasPath('sequencer', 'sent_to_tre'))
    sequencer_delete_after_confirmation: str | None = Field(default=None, validation_alias=AliasPath('sequencer', 'delete_after_confirmation'))
    status:         str
    created_at:     datetime
    updated_at:     datetime

    class Config:
        from_attributes = True
        populate_by_name = True
