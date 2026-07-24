from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.session import get_db
from db.repositories.settings import get_all, get_by_key, upsert
from schemas.settings import ShowSetting, UpdateSetting

router = APIRouter()


@router.get("/", response_model=list[ShowSetting])
def list_settings(db: Session = Depends(get_db)):
    return get_all(db)


@router.get("/{key}", response_model=ShowSetting)
def get_setting(key: str, db: Session = Depends(get_db)):
    s = get_by_key(key, db)
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Setting '{key}' not found")
    return s


@router.put("/{key}", response_model=ShowSetting)
def update_setting(key: str, body: UpdateSetting, db: Session = Depends(get_db)):
    try:
        return upsert(key, body.value, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
