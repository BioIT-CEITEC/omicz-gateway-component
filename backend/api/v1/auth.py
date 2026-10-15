import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import require_user
from core.logger import get_logger
from core.security import (create_access_token, verify_password, verify_password_or_dummy,
                           ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL)
from db.session import get_db
from db.models.users import Users
from db.repositories.users import (count_users, create_user, get_by_username, issue_refresh_token,
                                   rotate_refresh_token, revoke_refresh_token, set_password, TokenReused)
from schemas.users import LoginRequest, SetupRequest, RefreshRequest, TokenPair, ChangePassword, ShowUser

router = APIRouter()
logger = get_logger("backend")

FAILED_LOGIN_DELAY = 1.0  # seconds; slows down password guessing


def _tokens(user: Users, refresh_token: str) -> TokenPair:
    return TokenPair(access_token=create_access_token(user.uuid, user.username, user.is_admin),
                     refresh_token=refresh_token,
                     access_expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
                     refresh_expires_in=int(REFRESH_TOKEN_TTL.total_seconds()))


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """Whether the first administrator still has to be created (no account exists yet)."""
    return {"needs_setup": count_users(db) == 0}


@router.post("/setup", response_model=TokenPair)
def setup(body: SetupRequest, db: Session = Depends(get_db)):
    """Create the first administrator. Works only while no account exists."""
    if count_users(db) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup is already done")
    user = create_user(body.username, body.password, db, email=body.email, is_admin=True)
    logger.info(f"first administrator '{user.username}' created through the setup page")
    return _tokens(user, issue_refresh_token(user, db))


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = get_by_username(body.username, db)
    ok = verify_password_or_dummy(body.password, user.hashed_password if user else None)
    if not ok or not user.is_active:
        logger.warning(f"failed login for '{body.username}'")
        time.sleep(FAILED_LOGIN_DELAY)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password")
    logger.info(f"login: '{user.username}'")
    return _tokens(user, issue_refresh_token(user, db))


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        result = rotate_refresh_token(body.refresh_token, db)
    except TokenReused:
        logger.warning("a refresh token was used twice — all sessions of its user were ended")
        result = None
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user, nxt = result
    return _tokens(user, nxt)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    revoke_refresh_token(body.refresh_token, db)


@router.get("/me", response_model=ShowUser)
def me(user: Users = Depends(require_user)):
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePassword, user: Users = Depends(require_user), db: Session = Depends(get_db)):
    """Change your own password; every session, including this one, has to log in again."""
    if not verify_password(body.current_password, user.hashed_password):
        time.sleep(FAILED_LOGIN_DELAY)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password is wrong")
    set_password(user, body.new_password, db)
    logger.info(f"password changed: '{user.username}'")
