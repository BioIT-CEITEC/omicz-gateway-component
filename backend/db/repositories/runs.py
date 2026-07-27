from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from db.models.runs import Runs
from core.logger import get_logger

logger = get_logger("backend")


def create_run(name: str, sequencer_uuid: UUID, db: Session):
    """Called by the worker when a new run folder is detected."""
    run = Runs(name=name, sequencer_uuid=sequencer_uuid)
    try:
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Run '{name}' already exists for this sequencer"
        )


def update_run_status(name: str, sequencer_uuid: UUID, new_status: str, db: Session):
    """Called by the worker when RTAComplete.txt is detected."""
    run = (
        db.query(Runs)
        .filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid)
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{name}' not found for sequencer {sequencer_uuid}"
        )
    run.status = new_status
    db.commit()
    db.refresh(run)
    return run


def get_runs_by_sequencer(sequencer_uuid: UUID, db: Session):
    """Returns all active runs for a given sequencer."""
    return (
        db.query(Runs)
        .filter(Runs.sequencer_uuid == sequencer_uuid, Runs.is_deleted == False)
        .order_by(Runs.created_at.desc())
        .all()
    )


PIPELINE_STATUSES = ["queued", "checksumming", "moving", "verifying"]


def get_queued_runs(db: Session, skip: int = 0, limit: int = 20):
    """Returns paginated runs currently in the pipeline, active ones first then queued."""
    from sqlalchemy import case
    status_order = case(
        (Runs.status == "checksumming", 1),
        (Runs.status == "moving",       2),
        (Runs.status == "verifying",    3),
        (Runs.status == "queued",       4),
        else_=5,
    )
    return (
        db.query(Runs)
        .filter(Runs.status.in_(PIPELINE_STATUSES), Runs.is_deleted == False)
        .order_by(status_order, Runs.updated_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def count_queued_runs(db: Session) -> int:
    return (
        db.query(Runs)
        .filter(Runs.status.in_(PIPELINE_STATUSES), Runs.is_deleted == False)
        .count()
    )


FAILED_PIPELINE_STATUSES = ["move_failed", "verify_failed", "failed"]


def get_failed_pipeline_runs(db: Session) -> list:
    """Returns recently-failed runs that can be retried, newest first."""
    return (
        db.query(Runs)
        .filter(Runs.status.in_(FAILED_PIPELINE_STATUSES), Runs.is_deleted == False)
        .order_by(Runs.updated_at.desc())
        .limit(50)
        .all()
    )


def count_runs(db: Session, statuses: list[str] | None = None, search: str | None = None, sequencer_uuid=None) -> int:
    q = db.query(Runs).filter(Runs.is_deleted == False)
    if statuses:
        q = q.filter(Runs.status.in_(statuses))
    if search:
        q = q.filter(Runs.name.ilike(f"%{search}%"))
    if sequencer_uuid:
        q = q.filter(Runs.sequencer_uuid == sequencer_uuid)
    return q.count()


def get_all_runs(db: Session, skip: int = 0, limit: int = 20, statuses: list[str] | None = None, search: str | None = None, order: str = "desc", sequencer_uuid=None):
    """Returns all active runs across all sequencers."""
    q = db.query(Runs).filter(Runs.is_deleted == False)
    if statuses:
        q = q.filter(Runs.status.in_(statuses))
    if search:
        q = q.filter(Runs.name.ilike(f"%{search}%"))
    if sequencer_uuid:
        q = q.filter(Runs.sequencer_uuid == sequencer_uuid)
    sort_col = Runs.created_at.asc() if order == "asc" else Runs.created_at.desc()
    return q.order_by(sort_col).offset(skip).limit(limit).all()


def get_run_by_uuid(uuid: UUID, db: Session):
    run = db.query(Runs).filter(Runs.uuid == uuid, Runs.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def delete_run(uuid: UUID, db: Session):
    from db.repositories.runs_status_history import add_run_status_history
    run = db.query(Runs).filter(Runs.uuid == uuid, Runs.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    run.is_deleted = True
    db.commit()
    add_run_status_history(run_uuid=uuid, status="deleted", db=db)
    logger.info(f"soft-deleted run '{run.name}' (uuid={uuid})")

    return {"detail": "Run has been deleted"}
