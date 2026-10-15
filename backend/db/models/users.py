import uuid as uuid_lib
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base


class Users(Base):
    id   = Column(Integer, primary_key=True, index=True)
    uuid = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False, server_default="false", nullable=False)
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    sequencers = relationship("Sequencers", back_populates="author")
