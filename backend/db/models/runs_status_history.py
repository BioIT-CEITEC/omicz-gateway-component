import uuid as uuid_lib
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base


class RunsStatusHistory(Base):
    __tablename__ = "runs_status_history"

    id       = Column(Integer, primary_key=True, index=True)
    uuid     = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    run_uuid = Column(PG_UUID(as_uuid=True), ForeignKey("runs.uuid"), nullable=False, index=True)
    status   = Column(String, nullable=False)
    detail   = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    # relationship: a history entry belongs to one run
    run = relationship("Runs", back_populates="history")
