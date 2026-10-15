import os
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from core.logger import get_logger
from core.security import hash_password, new_refresh_token, hash_token, REFRESH_TOKEN_TTL
from db.models.users import Users
from db.models.refresh_tokens import RefreshTokens

logger = get_logger("backend")


class TokenReused(Exception):
    """A refresh token that was already used came back: it was copied, so all sessions of the user end."""


# ── Users ─────────────────────────────────────────────────────────────────────
def count_users(db: Session) -> int:
    return db.query(Users).filter(Users.is_deleted == False).count()


def get_by_username(username: str, db: Session) -> Users | None:
    return db.query(Users).filter(Users.username == username, Users.is_deleted == False).first()


def get_by_uuid(user_uuid, db: Session) -> Users | None:
    return db.query(Users).filter(Users.uuid == UUID(str(user_uuid)), Users.is_deleted == False).first()


def list_users(db: Session) -> list[Users]:
    return db.query(Users).filter(Users.is_deleted == False).order_by(Users.username).all()


def count_active_admins(db: Session) -> int:
    return db.query(Users).filter(Users.is_admin == True, Users.is_active == True, Users.is_deleted == False).count()


def create_user(username: str, password: str, db: Session, email: str | None = None, is_admin: bool = False,
                first_name: str | None = None, last_name: str | None = None) -> Users:
    user = Users(username=username, email=email or None, hashed_password=hash_password(password),
                 first_name=(first_name or '').strip() or None, last_name=(last_name or '').strip() or None,
                 is_active=True, is_admin=is_admin, created_at=datetime.now())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_password(user: Users, password: str, db: Session):
    """Change a password and end every session of the user."""
    user.hashed_password = hash_password(password)
    db.commit()
    revoke_all(user.uuid, db)


def ensure_admin_from_env(db: Session):
    """
    Create the admin account named in ADMIN_USERNAME / ADMIN_PASSWORD if it does not exist yet.
    An existing account is never changed, so a password changed in the web interface stays.
    """
    username, password = os.getenv("ADMIN_USERNAME"), os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        return
    if get_by_username(username, db):
        return
    create_user(username, password, db, is_admin=True)
    logger.info(f"created admin account '{username}' from ADMIN_USERNAME / ADMIN_PASSWORD")


# ── Refresh tokens ────────────────────────────────────────────────────────────
def issue_refresh_token(user: Users, db: Session) -> str:
    token = new_refresh_token()
    db.add(RefreshTokens(user_uuid=user.uuid, token_hash=hash_token(token),
                         expires_at=datetime.now() + REFRESH_TOKEN_TTL, created_at=datetime.now()))
    db.commit()
    return token


def rotate_refresh_token(token: str, db: Session) -> tuple[Users, str] | None:
    """
    Use a refresh token once: revoke it and return (user, next token). None if it is unknown,
    expired or its user can no longer log in. Raises TokenReused if it was already used.
    """
    row = db.query(RefreshTokens).filter(RefreshTokens.token_hash == hash_token(token)).first()
    if row is None:
        return None
    if row.revoked_at is not None:
        revoke_all(row.user_uuid, db)
        raise TokenReused()
    if row.expires_at <= datetime.now():
        return None
    user = get_by_uuid(row.user_uuid, db)
    if user is None or not user.is_active:
        return None
    nxt = new_refresh_token()
    row.revoked_at, row.replaced_by = datetime.now(), hash_token(nxt)
    db.add(RefreshTokens(user_uuid=user.uuid, token_hash=hash_token(nxt),
                         expires_at=datetime.now() + REFRESH_TOKEN_TTL, created_at=datetime.now()))
    db.commit()
    return user, nxt


def revoke_refresh_token(token: str, db: Session):
    row = db.query(RefreshTokens).filter(RefreshTokens.token_hash == hash_token(token)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now()
        db.commit()


def revoke_all(user_uuid, db: Session):
    db.query(RefreshTokens).filter(RefreshTokens.user_uuid == user_uuid, RefreshTokens.revoked_at == None) \
      .update({RefreshTokens.revoked_at: datetime.now()})
    db.commit()
