from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from db.models.sequencer_types import SequencerTypes
from schemas.sequencers_types import SequencerTypeCreate, SequencerTypeUpdate


def count_sequencers_type(db: Session) -> int:
    return db.query(SequencerTypes).filter(SequencerTypes.is_deleted == False).count()


def get_all_sequencers_type(db: Session, skip: int = 0, limit: int = 20):
    return db.query(SequencerTypes).filter(SequencerTypes.is_deleted == False).offset(skip).limit(limit).all()


def get_sequencer_type_by_uuid(uuid: UUID, db: Session):
    st = db.query(SequencerTypes).filter(SequencerTypes.uuid == uuid, SequencerTypes.is_deleted == False).first()
    if not st:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequencer type not found")
    return st


def create_sequencer_type(data: SequencerTypeCreate, db: Session):
    st = SequencerTypes(
        name=data.name,
        completion_signal=data.completion_signal,
        signal_match=data.signal_match,
    )
    try:
        db.add(st)
        db.commit()
        db.refresh(st)
        return st
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="A sequencer type with this name already exists")


def update_sequencer_type(uuid: UUID, data: SequencerTypeUpdate, db: Session):
    st = db.query(SequencerTypes).filter(SequencerTypes.uuid == uuid, SequencerTypes.is_deleted == False).first()
    if not st:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequencer type not found")
    if data.name is not None:
        st.name = data.name
    if data.completion_signal is not None:
        st.completion_signal = data.completion_signal
    if data.signal_match is not None:
        st.signal_match = data.signal_match
    try:
        db.commit()
        db.refresh(st)
        return st
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="A sequencer type with this name already exists")


def delete_sequencer_type(uuid: UUID, db: Session):
    st = db.query(SequencerTypes).filter(SequencerTypes.uuid == uuid, SequencerTypes.is_deleted == False).first()
    if not st:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequencer type not found")
    st.is_deleted = True
    db.commit()
    return {"detail": "Sequencer type has been deleted"}
