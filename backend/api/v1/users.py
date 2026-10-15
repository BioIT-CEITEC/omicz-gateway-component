from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import require_admin
from core.logger import get_logger
from db.session import get_db
from db.models.users import Users
from db.repositories.users import (list_users, create_user, get_by_uuid, count_active_admins,
                                   set_password, revoke_all)
from schemas.users import ShowUser, UserCreate, UserUpdate

router = APIRouter()
logger = get_logger("backend")


@router.get("/", response_model=list[ShowUser])
def all_users(db: Session = Depends(get_db), admin: Users = Depends(require_admin)):
    return list_users(db)


@router.post("/", response_model=ShowUser, status_code=status.HTTP_201_CREATED)
def add_user(body: UserCreate, db: Session = Depends(get_db), admin: Users = Depends(require_admin)):
    try:
        user = create_user(body.username, body.password, db, email=body.email, is_admin=body.is_admin)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this name or email already exists")
    logger.info(f"user '{user.username}' added by '{admin.username}' (admin={user.is_admin})")
    return user


@router.patch("/{uuid}", response_model=ShowUser)
def update_user(uuid: UUID, body: UserUpdate, db: Session = Depends(get_db), admin: Users = Depends(require_admin)):
    user = get_by_uuid(uuid, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    losing_admin = user.is_admin and user.is_active and (body.is_admin is False or body.is_active is False)
    if losing_admin and count_active_admins(db) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="At least one active administrator must remain")
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    db.commit()
    if body.is_active is False:
        revoke_all(user.uuid, db)
    if body.password:
        set_password(user, body.password, db)
    logger.info(f"user '{user.username}' changed by '{admin.username}': active={user.is_active} admin={user.is_admin}"
                f"{' password reset' if body.password else ''}")
    db.refresh(user)
    return user
