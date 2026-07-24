from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime

from db.base_class import Base


class Settings(Base):
    __tablename__ = "settings"

    key         = Column(String, primary_key=True)
    value       = Column(String, nullable=False)
    description = Column(Text, nullable=False, server_default="")
    category    = Column(String, nullable=False, server_default="general")
    updated_at  = Column(DateTime, default=datetime.now, onupdate=datetime.now)
