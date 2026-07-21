import uuid as uuid_lib
from sqlalchemy import Column, Integer, String, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base


class SequencerTypes(Base):
    __tablename__     = "sequencers_types"

    id   = Column(Integer, primary_key=True, index=True)
    uuid = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    name              = Column(String, index=True, nullable=False)

    completion_method = Column(String, nullable=False, default="signal", server_default="signal")

    #   "exact"  → filename == completion_signal     (e.g. RTAComplete.txt)
    #   "prefix" → filename.startswith(completion_signal) (e.g. final_summary_*)
    #   "suffix" → filename.endswith(completion_signal)
    completion_signal = Column(String, nullable=True)
    signal_match      = Column(String, nullable=False, default="exact", server_default="exact")

    # --- file_stability method fields (used when completion_method = "file_stability") ---
    stability_files             = Column(JSON, nullable=True)     # list of exact filenames to monitor
    stability_threshold_minutes = Column(Integer, nullable=True, default=10, server_default="10")

    is_deleted        = Column(Boolean, nullable=False, default=False, server_default="false")

    # reverse relationship: one type → many sequencers
    sequencers = relationship("Sequencers", back_populates="type", foreign_keys="[Sequencers.type_uuid]")
