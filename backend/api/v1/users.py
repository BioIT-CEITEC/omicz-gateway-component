from uuid import UUID

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from schemas.users import UserCreate, UserUpdate, ShowUser
from schemas.pagination import PaginatedResponse
from db.session import get_db
from db.repositories.users import create_new_user, get_all_users, count_users, get_user_by_uuid, update_user, delete_user, this_is_my_repository_test_fun
from core.config import settings

router = APIRouter()


@router.post("/", response_model=ShowUser, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    return create_new_user(user=user, db=db)


@router.get("/", response_model=PaginatedResponse[ShowUser])
def list_users(skip: int = Query(default=settings.PAGINATION_DEFAULT_SKIP, ge=0), limit: int = Query(default=settings.PAGINATION_DEFAULT_LIMIT, ge=1, le=settings.PAGINATION_MAX_LIMIT), db: Session = Depends(get_db)):
    return PaginatedResponse(
        total=count_users(db=db),
        skip=skip,
        limit=limit,
        results=get_all_users(db=db, skip=skip, limit=limit),
    )


# TEST. Alireza
@router.get("/test")
def test(db: Session = Depends(get_db), name = "AAA"):
    return this_is_my_repository_test_fun(db=db, name=name)



@router.get("/{uuid}", response_model=ShowUser)
def get_user(uuid: UUID, db: Session = Depends(get_db)):
    return get_user_by_uuid(uuid=uuid, db=db)


@router.patch("/{uuid}", response_model=ShowUser)
def patch_user(uuid: UUID, user: UserUpdate, db: Session = Depends(get_db)):
    return update_user(uuid=uuid, user=user, db=db)


@router.delete("/{uuid}", status_code=status.HTTP_200_OK)
def soft_delete_user(uuid: UUID, db: Session = Depends(get_db)):
    return delete_user(uuid=uuid, db=db)
