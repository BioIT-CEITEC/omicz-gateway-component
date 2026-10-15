from sqlalchemy import Column, String

from db.base_class import Base


class AppSecrets(Base):
    """Server-side secrets, such as the key that signs access tokens. Never exposed through the API."""
    __tablename__ = "app_secrets"

    key   = Column(String, primary_key=True)
    value = Column(String, nullable=False)
