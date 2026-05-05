from uuid import UUID

from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.orm import Session

from schemas.runs import ShowRun
from schemas.runs_status_history import ShowRunsStatusHistory
from schemas.pagination import PaginatedResponse
from db.session import get_db
from db.repositories.runs import get_all_runs, count_runs, get_run_by_uuid, get_runs_by_sequencer, delete_run
from db.repositories.runs_status_history import get_run_history
from services.publisher import publish
from core.config import settings

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[ShowRun])
def list_runs(skip: int = Query(default=settings.PAGINATION_DEFAULT_SKIP, ge=0), limit: int = Query(default=settings.PAGINATION_DEFAULT_LIMIT, ge=1, le=settings.PAGINATION_MAX_LIMIT), db: Session = Depends(get_db)):
    return PaginatedResponse(
        total=count_runs(db=db),
        skip=skip,
        limit=limit,
        results=get_all_runs(db=db, skip=skip, limit=limit),
    )


# NOTE: /sequencer/{sequencer_uuid} must be before /{uuid}
@router.get("/sequencer/{sequencer_uuid}", response_model=list[ShowRun])
def list_runs_by_sequencer(sequencer_uuid: UUID, db: Session = Depends(get_db)):
    return get_runs_by_sequencer(sequencer_uuid=sequencer_uuid, db=db)


# NOTE: /{uuid}/history must be before /{uuid} — otherwise FastAPI matches "history" as a UUID path param
@router.get("/{uuid}/history", response_model=list[ShowRunsStatusHistory])
def get_history(uuid: UUID, db: Session = Depends(get_db)):
    return get_run_history(run_uuid=uuid, db=db)


@router.get("/{uuid}", response_model=ShowRun)
def get_run(uuid: UUID, db: Session = Depends(get_db)):
    return get_run_by_uuid(uuid=uuid, db=db)


@router.post("/{uuid}/start-zipping", status_code=status.HTTP_202_ACCEPTED)
def start_zipping(uuid: UUID, db: Session = Depends(get_db)):
    """
    Manual trigger: start zipping and move to TRE.
    Only valid when run status is 'running_finished'.
    Returns 409 if the run is not in the expected state.
    """
    run = get_run_by_uuid(uuid=uuid, db=db)
    if run.status != "running_finished":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot start zipping: run is '{run.status}', expected 'running_finished'"
        )
    publish("run_zip_requested", run.name, run.sequencer_uuid)
    return {"detail": "Zipping started"}


@router.post("/{uuid}/confirm-delete", status_code=status.HTTP_202_ACCEPTED)
def confirm_delete(uuid: UUID, db: Session = Depends(get_db)):
    """
    Manual trigger: confirm the zip was received in TRE and delete the local copy.
    Only valid when run status is 'confirmation'.
    Returns 409 if the run is not in the expected state.
    """
    run = get_run_by_uuid(uuid=uuid, db=db)
    if run.status != "confirmation":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot confirm delete: run is '{run.status}', expected 'confirmation'"
        )
    publish("run_delete_requested", run.name, run.sequencer_uuid)
    return {"detail": "Delete confirmed"}


@router.delete("/{uuid}", status_code=status.HTTP_200_OK)
def soft_delete_run(uuid: UUID, db: Session = Depends(get_db)):
    return delete_run(uuid=uuid, db=db)
