"""
Cancel while a run is uploading: the upload stops within seconds instead of running on in the
background, and a finished or stopped upload never overwrites the status the user set.
"""
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # noqa: F401
from db.models.runs import Runs
from db.models.run_files import RunFiles
from db.models.runs_status_history import RunsStatusHistory
from services import worker, tre
from test_multipart_upload import FakeS3, MIB


# ── boto3 engine ──────────────────────────────────────────────────────────────

@pytest.fixture
def boto3_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(tre, "_MULTIPART_THRESHOLD", 1 * MIB)
    monkeypatch.setattr(tre, "_MULTIPART_CHUNKSIZE", 1 * MIB)
    monkeypatch.setattr(tre, "_MULTIPART_CONCURRENCY", 1)          # parts one by one, so the stop point is exact
    monkeypatch.setattr(tre, "_check_endpoint", lambda: None)
    monkeypatch.setattr(tre.time, "sleep", lambda s: None)
    monkeypatch.setattr(tre, "get_setting_str", lambda key, default: "boto3")
    monkeypatch.setattr(tre, "get_setting_int", lambda key, default: default)
    s3 = FakeS3()
    monkeypatch.setattr(tre, "_upload_client", lambda: s3)
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(6 * MIB))
    return s3, [(str(big), "RUN/big.bin")]


def test_cancel_aborts_a_multipart_upload_after_the_current_part(boto3_engine):
    s3, files = boto3_engine
    checks = [0]

    def should_stop():                                # like the worker's: stays True once cancelled
        checks[0] += 1
        return checks[0] >= 4                         # before the file, after parts 1 and 2 → cancel after part 3

    with pytest.raises(tre.UploadCancelled):
        tre.upload_file_list(files, "slug", should_stop=should_stop)
    assert s3.calls[:3] == [1, 2, 3]
    assert len(s3.calls) <= 3 + tre._MULTIPART_CONCURRENCY   # a part already started may still go; no retries
    assert len(set(s3.calls)) == len(s3.calls) < 6
    assert s3.aborted and s3.completed is None


def test_cancel_before_a_file_sends_nothing(boto3_engine):
    s3, files = boto3_engine
    with pytest.raises(tre.UploadCancelled):
        tre.upload_file_list(files, "slug", should_stop=lambda: True)
    assert s3.calls == []


# ── worker ────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    for t in (Runs, RunFiles, RunsStatusHistory):
        t.__table__.create(engine)
    make = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, "SESSION_LOCAL", make)
    seq = SimpleNamespace(uuid=uuid4(), location="/runs/m1", slug="m1", exclusions=[])
    monkeypatch.setattr(worker, "get_sequencer", lambda uuid: seq)
    session = make()
    session.seq = seq
    yield session
    session.close()


def set_status(db, run, status):
    """What Cancel / Retry do in the API, from another session."""
    other = worker.SESSION_LOCAL()
    other.query(Runs).filter(Runs.uuid == run.uuid).update({"status": status})
    other.commit()
    other.close()


def queued_run(db):
    run = Runs(name="R", sequencer_uuid=db.seq.uuid, status="queued")
    db.add(run)
    db.commit()
    return run


def status_of(db, run):
    return db.query(Runs).filter(Runs.uuid == run.uuid).one().status


def history(db, run):
    db.expire_all()
    return [h.status for h in db.query(RunsStatusHistory).filter_by(run_uuid=run.uuid).order_by(RunsStatusHistory.created_at)]


def test_stop_check_follows_the_run_status(db):
    run = queued_run(db)
    set_status(db, run, "moving")
    should_stop = worker._make_stop_check(run.uuid, interval=0)
    assert should_stop() is False
    set_status(db, run, "move_failed")                # Cancel
    assert should_stop() is True


def test_cancelled_upload_stops_and_keeps_the_users_status(db, monkeypatch):
    run = queued_run(db)

    def send_to_tre(**kw):
        set_status(db, run, "move_failed")            # Cancel, then Retry
        set_status(db, run, "queued")
        assert kw["should_stop"]() is True
        raise tre.UploadCancelled()

    monkeypatch.setattr(worker, "send_to_tre", send_to_tre)
    worker.handle_run_upload_requested("R", db.seq.uuid)

    db.expire_all()
    assert status_of(db, run) == "queued"
    assert history(db, run) == ["moving"]             # no move_failed, no verifying from the worker


def test_upload_finishing_after_cancel_does_not_set_verifying(db, monkeypatch):
    run = queued_run(db)
    monkeypatch.setattr(worker, "send_to_tre", lambda **kw: set_status(db, run, "move_failed"))
    worker.handle_run_upload_requested("R", db.seq.uuid)

    db.expire_all()
    assert status_of(db, run) == "move_failed"
    assert "verifying" not in history(db, run)


def test_upload_without_cancel_still_goes_to_verifying(db, monkeypatch):
    run = queued_run(db)
    monkeypatch.setattr(worker, "send_to_tre", lambda **kw: None)
    worker.handle_run_upload_requested("R", db.seq.uuid)

    db.expire_all()
    assert status_of(db, run) == "verifying"
