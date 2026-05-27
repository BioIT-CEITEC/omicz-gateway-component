from uuid import UUID

from sqlalchemy.orm import Session

from db.models.runs_status_history import RunsStatusHistory


def add_run_status_history(run_uuid: UUID, status: str, db: Session, detail: str | None = None):
    """Insert a status history entry for a run."""
    entry = RunsStatusHistory(run_uuid=run_uuid, status=status, detail=detail)
    db.add(entry)
    db.commit()


def get_run_history(run_uuid: UUID, db: Session):
    """Returns all status history entries for a run, oldest first."""
    return (
        db.query(RunsStatusHistory)
        .filter(RunsStatusHistory.run_uuid == run_uuid)
        .order_by(RunsStatusHistory.created_at.asc())
        .all()
    )
