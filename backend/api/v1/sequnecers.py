from uuid import UUID

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from schemas.sequencers import SequencerCreate, SequencerUpdate, ShowSequencer
from schemas.pagination import PaginatedResponse
from db.session import get_db
from db.repositories.sequencers import create_new_sequencer, get_all_sequencers, count_sequencers, get_sequencer_by_uuid, update_sequencer, delete_sequencer
from core.config import settings

router = APIRouter()


@router.post("/", response_model=ShowSequencer, status_code=status.HTTP_201_CREATED)
def create_sequencer(sequencer: SequencerCreate, db: Session = Depends(get_db)):
    return create_new_sequencer(sequencer=sequencer, db=db)


@router.get("/", response_model=PaginatedResponse[ShowSequencer])
def list_sequencers(skip: int = Query(default=settings.PAGINATION_DEFAULT_SKIP, ge=0), limit: int = Query(default=settings.PAGINATION_DEFAULT_LIMIT, ge=1, le=settings.PAGINATION_MAX_LIMIT), db: Session = Depends(get_db)):
    return PaginatedResponse(
        total=count_sequencers(db=db),
        skip=skip,
        limit=limit,
        results=get_all_sequencers(db=db, skip=skip, limit=limit),
    )


@router.get("/{uuid}", response_model=ShowSequencer)
def get_sequencer(uuid: UUID, db: Session = Depends(get_db)):
    return get_sequencer_by_uuid(uuid=uuid, db=db)


@router.patch("/{uuid}", response_model=ShowSequencer)
def patch_sequencer(uuid: UUID, sequencer: SequencerUpdate, db: Session = Depends(get_db)):
    return update_sequencer(uuid=uuid, sequencer=sequencer, db=db)


@router.post("/{uuid}/toggle-status", response_model=ShowSequencer)
def toggle_sequencer_status(uuid: UUID, db: Session = Depends(get_db)):
    """Toggle sequencer status between 'active' and 'inactive'."""
    sequencer = get_sequencer_by_uuid(uuid=uuid, db=db)
    new_status = "inactive" if sequencer.status == "active" else "active"
    from schemas.sequencers import SequencerUpdate
    return update_sequencer(uuid=uuid, sequencer=SequencerUpdate(status=new_status), db=db)


@router.delete("/{uuid}", status_code=status.HTTP_200_OK)
def soft_delete_sequencer(uuid: UUID, db: Session = Depends(get_db)):
    return delete_sequencer(uuid=uuid, db=db)
