from uuid import UUID

from sqlalchemy.orm import Session
from schemas.users import UserCreate, UserUpdate
from db.models.users import Users
from core.hashing import Hasher
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status


def create_new_user(user: UserCreate, db: Session):
    user = Users(
        email=user.email,
        username=user.username,
        is_active=True,
        hashed_password=Hasher.get_hashed_password(user.password)
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Username or Email already registered"
        )


def count_users(db: Session) -> int:
    return db.query(Users).filter(Users.is_deleted == False).count()


def get_all_users(db: Session, skip: int = 0, limit: int = 20):
    return db.query(Users).filter(Users.is_deleted == False).offset(skip).limit(limit).all()


def get_user_by_uuid(uuid: UUID, db: Session):
    user = db.query(Users).filter(Users.uuid == uuid, Users.is_deleted == False).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found")
    return user


def update_user(uuid: UUID, user: UserUpdate, db: Session):
    existing = db.query(Users).filter(Users.uuid == uuid, Users.is_deleted == False).first()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found")
    if user.username is not None:
        existing.username = user.username
    if user.email is not None:
        existing.email = user.email
    if user.password is not None:
        existing.hashed_password = Hasher.get_hashed_password(user.password)
    try:
        db.commit()
        db.refresh(existing)
        return existing
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Username or Email already registered")


def delete_user(uuid: UUID, db: Session):
    user = db.query(Users).filter(Users.uuid == uuid, Users.is_deleted == False).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found")
    user.is_deleted = True
    db.commit()
    return {"detail": "User has been deleted"}



def this_is_my_repository_test_fun(db: Session, name: str, skip: int = 0, limit: int = 20):
    return db.query(Users).distinct().all()
    # return {"message": f"This is a test endpoint for users, {name}.", "uuid": "123e4567-e89b-12d3-a456-426614174000"}
