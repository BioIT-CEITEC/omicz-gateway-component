from uuid import UUID
from pydantic import BaseModel, model_validator
from typing import Literal, List


class SequencerTypeCreate(BaseModel):
    name:               str
    completion_method:  Literal["signal", "file_stability"] = "signal"

    # signal method fields
    completion_signal:  str | None = None
    signal_match:       Literal["exact", "prefix", "suffix"] = "exact"

    # file_stability method fields
    stability_files:             List[str] | None = None
    stability_threshold_minutes: int | None = 10

    @model_validator(mode="after")
    def check_method_fields(self):
        if self.completion_method == "signal" and not self.completion_signal:
            raise ValueError("completion_signal is required when completion_method is 'signal'")
        if self.completion_method == "file_stability" and not self.stability_files:
            raise ValueError("stability_files is required when completion_method is 'file_stability'")
        return self


class SequencerTypeUpdate(BaseModel):
    name:               str | None = None
    completion_method:  Literal["signal", "file_stability"] | None = None
    completion_signal:  str | None = None
    signal_match:       Literal["exact", "prefix", "suffix"] | None = None
    stability_files:             List[str] | None = None
    stability_threshold_minutes: int | None = None


class ShowSequencerType(BaseModel):
    id:                 int
    uuid:               UUID
    name:               str
    completion_method:  str
    completion_signal:  str | None
    signal_match:       str
    stability_files:             List[str] | None
    stability_threshold_minutes: int | None

    class Config:
        from_attributes = True
