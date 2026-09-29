from uuid import UUID
from pydantic import BaseModel, model_validator
from typing import Literal, List


def check_directory_timers(dir_minutes: int | None, run_minutes: int | None):
    if not dir_minutes or dir_minutes < 1 or not run_minutes or run_minutes < 1:
        raise ValueError("dir_stability_minutes and run_stability_minutes must be at least 1")
    if dir_minutes >= run_minutes:
        raise ValueError("dir_stability_minutes must be shorter than run_stability_minutes")


class SequencerTypeCreate(BaseModel):
    name:               str
    completion_method:  Literal["signal", "file_stability", "directory_stability"] = "signal"

    # signal method fields
    completion_signal:  str | None = None
    signal_match:       Literal["exact", "prefix", "suffix"] = "exact"

    # file_stability method fields
    stability_files:             List[str] | None = None
    stability_threshold_minutes: int | None = 10

    # directory_stability method fields
    dir_stability_minutes: int | None = 10
    run_stability_minutes: int | None = 60

    @model_validator(mode="after")
    def check_method_fields(self):
        if self.completion_method == "signal" and not self.completion_signal:
            raise ValueError("completion_signal is required when completion_method is 'signal'")
        if self.completion_method == "file_stability" and not self.stability_files:
            raise ValueError("stability_files is required when completion_method is 'file_stability'")
        if self.completion_method == "directory_stability":
            check_directory_timers(self.dir_stability_minutes, self.run_stability_minutes)
        return self


class SequencerTypeUpdate(BaseModel):
    name:               str | None = None
    completion_method:  Literal["signal", "file_stability", "directory_stability"] | None = None
    completion_signal:  str | None = None
    signal_match:       Literal["exact", "prefix", "suffix"] | None = None
    stability_files:             List[str] | None = None
    stability_threshold_minutes: int | None = None
    dir_stability_minutes: int | None = None
    run_stability_minutes: int | None = None


class ShowSequencerType(BaseModel):
    id:                 int
    uuid:               UUID
    name:               str
    completion_method:  str
    completion_signal:  str | None
    signal_match:       str
    stability_files:             List[str] | None
    stability_threshold_minutes: int | None
    dir_stability_minutes: int | None = None
    run_stability_minutes: int | None = None

    class Config:
        from_attributes = True
