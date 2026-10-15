from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from db.base_class import Base


class RefreshTokens(Base):
    """
    One row per refresh token. Only the SHA-256 of the token is stored, so a copy of the
    database cannot be used to log in. A token is used once: refreshing revokes it and
    issues the next one (replaced_by), and presenting a revoked token again revokes every
    token of that user, because it means the token was copied.
    """
    __tablename__ = "refresh_tokens"

    id          = Column(Integer, primary_key=True, index=True)
    user_uuid   = Column(PG_UUID(as_uuid=True), ForeignKey("users.uuid"), nullable=False, index=True)
    token_hash  = Column(String(64), unique=True, nullable=False, index=True)
    expires_at  = Column(DateTime, nullable=False)
    created_at  = Column(DateTime, default=datetime.now)
    revoked_at  = Column(DateTime, nullable=True)
    replaced_by = Column(String(64), nullable=True)
