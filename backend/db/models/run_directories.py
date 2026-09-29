import uuid as uuid_lib
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from db.base_class import Base


class RunDirectories(Base):
    """
    One row per top-level directory of a run whose instrument model uses
    completion_method = "directory_stability".

    state:
      waiting   → directory is still changing, or quiet for less than dir_stability_minutes
      queued    → quiet long enough, run_directory_upload_requested published
      uploading → worker is hashing + uploading its files
      sent      → all files uploaded
      failed    → upload error (files not yet uploaded are picked up at finalization or by Retry)
      conflict  → an already-uploaded file was modified or deleted — needs a person
    """
    __tablename__ = "run_directories"
    __table_args__ = (UniqueConstraint("run_uuid", "name", name="uq_run_directories_run_name"),)

    id           = Column(Integer, primary_key=True, index=True)
    uuid         = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid_lib.uuid4)
    run_uuid     = Column(PG_UUID(as_uuid=True), ForeignKey("runs.uuid"), nullable=False, index=True)
    name         = Column(String, nullable=False)
    state        = Column(String, nullable=False, default="waiting", server_default="waiting")
    fingerprint  = Column(String, nullable=True)   # sha1 over (path, size, mtime) of every file inside
    stable_since = Column(DateTime, nullable=True)  # last time the fingerprint changed
    file_count   = Column(Integer, nullable=False, default=0, server_default="0")
    total_bytes  = Column(BigInteger, nullable=False, default=0, server_default="0")
    progress     = Column(Text, nullable=True)
    detail       = Column(Text, nullable=True)
    sent_at      = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.now)
    updated_at   = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    run = relationship("Runs", back_populates="directories")
