import uuid as uuid_lib
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base


class Runs(Base):
    id   = Column(Integer, primary_key=True, index=True)
    uuid = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    name         = Column(String, nullable=False)
    sequencer_uuid = Column(PG_UUID(as_uuid=True), ForeignKey("sequencers.uuid"), nullable=False)
    status       = Column(String, nullable=False, default="running", server_default="running")
    is_deleted   = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at   = Column(DateTime, default=datetime.now)
    updated_at   = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # relationship: a run belongs to one sequencer
    sequencer = relationship("Sequencers", back_populates="runs")

    # relationship: a run has many status history entries
    history = relationship("RunsStatusHistory", back_populates="run")
