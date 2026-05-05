from uuid import UUID

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from db.session import get_db
from core.config import settings
from db.repositories.sequencers_types import (
    get_all_sequencers_type,
    count_sequencers_type,
    get_sequencer_type_by_uuid,
    create_sequencer_type,
    update_sequencer_type,
    delete_sequencer_type,
)
from schemas.sequencers_types import ShowSequencerType, SequencerTypeCreate, SequencerTypeUpdate
from schemas.pagination import PaginatedResponse

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[ShowSequencerType])
def list_sequencer_types(skip: int = Query(default=settings.PAGINATION_DEFAULT_SKIP, ge=0), limit: int = Query(default=settings.PAGINATION_DEFAULT_LIMIT, ge=1, le=settings.PAGINATION_MAX_LIMIT), db: Session = Depends(get_db)):
    return PaginatedResponse(
        total=count_sequencers_type(db=db),
        skip=skip,
        limit=limit,
        results=get_all_sequencers_type(db=db, skip=skip, limit=limit),
    )


@router.post("/", response_model=ShowSequencerType, status_code=status.HTTP_201_CREATED)
def create_sequencer_type_endpoint(data: SequencerTypeCreate, db: Session = Depends(get_db)):
    return create_sequencer_type(data=data, db=db)


@router.get("/{uuid}", response_model=ShowSequencerType)
def get_sequencer_type(uuid: UUID, db: Session = Depends(get_db)):
    return get_sequencer_type_by_uuid(uuid=uuid, db=db)


@router.patch("/{uuid}", response_model=ShowSequencerType)
def update_sequencer_type_endpoint(uuid: UUID, data: SequencerTypeUpdate, db: Session = Depends(get_db)):
    return update_sequencer_type(uuid=uuid, data=data, db=db)


@router.delete("/{uuid}", status_code=status.HTTP_200_OK)
def hard_delete_sequencer_type(uuid: UUID, db: Session = Depends(get_db)):
    return delete_sequencer_type(uuid=uuid, db=db)
