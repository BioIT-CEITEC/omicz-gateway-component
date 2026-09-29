from sqlalchemy import Column, Integer, BigInteger, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from db.base_class import Base


class RunFiles(Base):
    """
    Per-file record for files sent early by directory stability.
    (size, mtime_ns) is the file state at hashing time — it lets finalization
    reuse the digest instead of re-hashing, skip the re-upload, and lets the
    watcher detect files that changed after they were sent.
    """
    __tablename__ = "run_files"
    __table_args__ = (UniqueConstraint("run_uuid", "rel_path", name="uq_run_files_run_path"),)

    id       = Column(Integer, primary_key=True, index=True)
    run_uuid = Column(PG_UUID(as_uuid=True), ForeignKey("runs.uuid"), nullable=False, index=True)
    rel_path = Column(String, nullable=False)   # relative to the run folder, "/" separated
    size     = Column(BigInteger, nullable=False)
    mtime_ns = Column(BigInteger, nullable=False)
    sha256   = Column(String(64), nullable=False)
    uploaded = Column(Boolean, nullable=False, default=False, server_default="false")
