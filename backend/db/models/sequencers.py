import uuid as uuid_lib
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base

class Sequencers(Base):
    id   = Column(Integer, primary_key=True, index=True)
    uuid = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    name = Column(String, index=True, nullable=False)
    slug = Column(String, index=True, nullable=False)
    location = Column(String, nullable=False)
    author_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    type_uuid  = Column(PG_UUID(as_uuid=True), ForeignKey("sequencers_types.uuid"), nullable=True)
    author     = relationship("Users", back_populates="sequencers")
    type       = relationship("SequencerTypes", back_populates="sequencers", foreign_keys=[type_uuid])
    runs      = relationship("Runs", back_populates="sequencer")
    status = Column(String, nullable=False, default="active")
    sent_to_tre             = Column(String, nullable=False, default="manual")
    exclusions              = Column(JSON, nullable=True)
    delete_after_confirmation = Column(String, nullable=False, default="manual")
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

