import uuid as uuid_lib
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base


class SequencerTypes(Base):
    __tablename__     = "sequencers_types"

    id   = Column(Integer, primary_key=True, index=True)
    uuid = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    name              = Column(String, index=True, nullable=False)
    completion_signal = Column(String, nullable=False)

    # how to match the filename against completion_signal:
    #   "exact"  → filename == completion_signal     (e.g. RTAComplete.txt)
    #   "prefix" → filename.startswith(completion_signal) (e.g. final_summary_*)
    signal_match      = Column(String, nullable=False, default="exact", server_default="exact")
    is_deleted        = Column(Boolean, nullable=False, default=False, server_default="false")

    # reverse relationship: one type → many sequencers
    sequencers = relationship("Sequencers", back_populates="type", foreign_keys="[Sequencers.type_uuid]")
