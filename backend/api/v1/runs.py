from uuid import UUID

from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.orm import Session

from schemas.runs import ShowRun
from schemas.runs_status_history import ShowRunsStatusHistory
from schemas.pagination import PaginatedResponse
from db.session import get_db
from db.repositories.runs import get_all_runs, count_runs, get_run_by_uuid, get_runs_by_sequencer, delete_run, get_queued_runs, count_queued_runs, get_failed_pipeline_runs
from db.repositories.runs_status_history import get_run_history, add_run_status_history
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


# NOTE: fixed-path routes must come before /{uuid}
@router.get("/queue", response_model=PaginatedResponse[ShowRun])
def get_queue(skip: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    """Returns paginated runs currently in the pipeline (queued + active)."""
    return PaginatedResponse(
        total=count_queued_runs(db=db),
        skip=skip,
        limit=limit,
        results=get_queued_runs(db=db, skip=skip, limit=limit),
    )


@router.get("/failed", response_model=list[ShowRun])
def get_failed(db: Session = Depends(get_db)):
    """Returns recently-failed pipeline runs (move_failed, verify_failed, failed)."""
    return get_failed_pipeline_runs(db=db)


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


@router.post("/{uuid}/start-upload", status_code=status.HTTP_202_ACCEPTED)
def start_upload(uuid: UUID, db: Session = Depends(get_db)):
    """
    Manual trigger: start checksum generation then upload to TRE.
    Sets status to 'queued' immediately so the UI reflects the pending state.
    """
    run = get_run_by_uuid(uuid=uuid, db=db)
    if run.status not in ("running_finished", "move_failed", "verify_failed", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot start upload: run is '{run.status}'"
        )
    prev_status = run.status
    run.status = "queued"
    db.commit()
    db.refresh(run)
    add_run_status_history(run_uuid=run.uuid, status="queued", db=db)
    if prev_status == "verify_failed":
        publish("run_verify_requested", run.name, run.sequencer_uuid)
    else:
        publish("run_checksum_requested", run.name, run.sequencer_uuid)
    return {"detail": "Queued"}


@router.post("/{uuid}/recheck", status_code=status.HTTP_202_ACCEPTED)
def recheck(uuid: UUID, db: Session = Depends(get_db)):
    """
    Force a fresh checksum after verify_failed.
    Deletes the existing .CHECKSUM file and restarts the full pipeline.
    """
    run = get_run_by_uuid(uuid=uuid, db=db)
    if run.status not in ("verify_failed", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot recheck: run is '{run.status}'"
        )
    run.status = "queued"
    db.commit()
    db.refresh(run)
    add_run_status_history(run_uuid=run.uuid, status="queued", db=db)
    publish("run_rechecksum_requested", run.name, run.sequencer_uuid)
    return {"detail": "Queued"}


@router.delete("/{uuid}", status_code=status.HTTP_200_OK)
def soft_delete_run(uuid: UUID, db: Session = Depends(get_db)):
    return delete_run(uuid=uuid, db=db)
