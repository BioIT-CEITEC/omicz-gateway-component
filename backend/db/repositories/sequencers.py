from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from schemas.sequencers import SequencerCreate, SequencerUpdate
from db.models.sequencers import Sequencers


def create_new_sequencer(sequencer: SequencerCreate, db: Session):
    sequencer = Sequencers(
        name=sequencer.name,
        slug=sequencer.slug,
        location=sequencer.location,
        author_id=sequencer.author_id,
        type_uuid=sequencer.type_uuid,
        status=sequencer.status,
        sent_to_tre=sequencer.sent_to_tre,
    )
    try:
        db.add(sequencer)
        db.commit()
        db.refresh(sequencer)
        return sequencer
    except IntegrityError as e:
        db.rollback()
        error = str(e.orig)
        if "unique" in error.lower():
            detail = "Sequencer with this name or slug already exists"
        elif "foreign key" in error.lower():
            detail = "author_id does not reference a valid user"
        else:
            detail = f"Database error: {error}"
        raise HTTPException(status_code=400, detail=detail)


def count_sequencers(db: Session) -> int:
    return db.query(Sequencers).filter(Sequencers.is_deleted == False).count()


def get_all_sequencers(db: Session, skip: int = 0, limit: int = 20):
    return db.query(Sequencers).filter(Sequencers.is_deleted == False).offset(skip).limit(limit).all()


def get_sequencer_by_uuid(uuid: UUID, db: Session):
    sequencer = db.query(Sequencers).filter(Sequencers.uuid == uuid, Sequencers.is_deleted == False).first()
    if not sequencer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequencer not found")
    return sequencer


def update_sequencer(uuid: UUID, sequencer: SequencerUpdate, db: Session):
    existing = db.query(Sequencers).filter(Sequencers.uuid == uuid, Sequencers.is_deleted == False).first()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequencer not found")
    if sequencer.name is not None:
        existing.name = sequencer.name
    if sequencer.slug is not None:
        existing.slug = sequencer.slug
    if sequencer.location is not None:
        existing.location = sequencer.location
    if sequencer.author_id is not None:
        existing.author_id = sequencer.author_id
    if sequencer.type_uuid is not None:
        existing.type_uuid = sequencer.type_uuid
    if sequencer.status is not None:
        existing.status = sequencer.status
    if sequencer.sent_to_tre is not None:
        existing.sent_to_tre = sequencer.sent_to_tre
    try:
        db.commit()
        db.refresh(existing)
        return existing
    except IntegrityError as e:
        db.rollback()
        error = str(e.orig)
        if "unique" in error.lower():
            detail = "Sequencer with this name or slug already exists"
        elif "foreign key" in error.lower():
            detail = "author_id does not reference a valid user"
        else:
            detail = f"Database error: {error}"
        raise HTTPException(status_code=400, detail=detail)


def delete_sequencer(uuid: UUID, db: Session):
    sequencer = db.query(Sequencers).filter(Sequencers.uuid == uuid, Sequencers.is_deleted == False).first()
    if not sequencer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequencer not found")
    sequencer.is_deleted = True
    db.commit()
    return {"detail": "Sequencer has been deleted"}
