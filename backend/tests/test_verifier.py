"""
TRE verification runs in the worker's verifier thread, outside the pipeline queue.
check_verifying_run does one single-shot S3 check per call.
"""
import os
import sys
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # noqa: F401
from db.models.runs import Runs
from db.models.runs_status_history import RunsStatusHistory
from db.models.run_files import RunFiles
from services import worker

T0 = datetime(2026, 9, 29, 12, 0, 0)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Runs.__table__.create(engine)
    RunsStatusHistory.__table__.create(engine)
    RunFiles.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    settings = {}  # no rows → the code's own defaults apply
    monkeypatch.setattr(worker, "get_setting_int", lambda key, default: settings.get(key, default))
    monkeypatch.setattr(worker, "get_sequencer", lambda uuid: None)
    yield session
    session.close()


def verifying_run(db, checksum_file="abc.CHECKSUM", since=T0):
    run = Runs(name="RUN_1", sequencer_uuid=uuid4(), status="verifying", checksum_file=checksum_file)
    db.add(run)
    db.commit()
    db.add(RunsStatusHistory(run_uuid=run.uuid, status="verifying", created_at=since))
    db.commit()
    return run


def tre_answers(monkeypatch, result):
    monkeypatch.setattr(worker, "check_verify_status", lambda name: result)


def last_history(db):
    return db.query(RunsStatusHistory).order_by(RunsStatusHistory.id.desc()).first()


def test_confirmed_run_completes(db, monkeypatch):
    run = verifying_run(db)
    tre_answers(monkeypatch, {"status": "success"})
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=3))
    assert run.status == "completed"
    assert last_history(db).status == "completed"


def test_tre_error_fails_with_detail(db, monkeypatch):
    run = verifying_run(db)
    tre_answers(monkeypatch, {"status": "failed", "detail": "manifest mismatch"})
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=3))
    assert run.status == "verify_failed"
    assert last_history(db).detail == "manifest mismatch"


def test_pending_keeps_waiting_until_default_one_hour(db, monkeypatch):
    run = verifying_run(db)
    tre_answers(monkeypatch, {"status": "pending"})
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=59, seconds=59))
    assert run.status == "verifying"
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=60))
    assert run.status == "verify_failed"
    assert "not received within 60 min" in last_history(db).detail


def test_s3_error_is_retried_not_failed(db, monkeypatch):
    run = verifying_run(db)
    tre_answers(monkeypatch, {"status": "error", "detail": "timeout"})
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=1))
    assert run.status == "verifying"


def test_retry_restarts_the_wait(db, monkeypatch):
    """A newer 'verifying' history entry (Retry Verification) resets the timeout."""
    run = verifying_run(db, since=T0)
    db.add(RunsStatusHistory(run_uuid=run.uuid, status="verifying", created_at=T0 + timedelta(minutes=90)))
    db.commit()
    tre_answers(monkeypatch, {"status": "pending"})
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=95))
    assert run.status == "verifying"


def test_missing_checksum_name_fails(db, monkeypatch):
    run = verifying_run(db, checksum_file=None)
    tre_answers(monkeypatch, {"status": "success"})
    worker.check_verifying_run(run, db)
    assert run.status == "verify_failed"


def test_does_not_override_a_status_changed_meanwhile(db, monkeypatch):
    run = verifying_run(db)
    db.query(Runs).filter(Runs.uuid == run.uuid).update({"status": "move_failed"})
    db.commit()
    tre_answers(monkeypatch, {"status": "success"})
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=1))
    db.refresh(run)
    assert run.status == "move_failed"
