import os
import shutil
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from db.models.runs import Runs
from db.models.sequencers import Sequencers
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


def count_runs(db: Session) -> int:
    return db.query(Runs).filter(Runs.is_deleted == False).count()


def get_all_runs(db: Session, skip: int = 0, limit: int = 20):
    """Returns all active runs across all sequencers."""
    return (
        db.query(Runs)
        .filter(Runs.is_deleted == False)
        .order_by(Runs.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_run_by_uuid(uuid: UUID, db: Session):
    run = db.query(Runs).filter(Runs.uuid == uuid, Runs.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def delete_run(uuid: UUID, db: Session):
    run = db.query(Runs).filter(Runs.uuid == uuid, Runs.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # save these before the session changes state
    run_name = run.name
    sequencer_uuid = run.sequencer_uuid

    # soft delete first — this must always succeed regardless of filesystem state
    run.is_deleted = True
    db.commit()

    # now separately query the sequencer to get its location — no lazy loading
    sequencer = db.query(Sequencers).filter(Sequencers.uuid == sequencer_uuid).first()
    if sequencer and sequencer.location:
        run_folder = os.path.join(sequencer.location, run_name)
        if os.path.isdir(run_folder):
            try:
                shutil.rmtree(run_folder)
                logger.info(f"deleted run folder: {run_folder}")
            except Exception as e:
                logger.error(f"failed to delete run folder '{run_folder}': {e}", exc_info=True)
        else:
            logger.warning(f"run folder not found on disk, skipping: {run_folder}")

    return {"detail": "Run has been deleted"}
