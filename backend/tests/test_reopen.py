"""
Tests for reopening completed runs when new files appear (services/reopen.py).

Run inside the backend container:
    docker exec fastapi_gateway_backend python -m pytest tests -q
"""
import os
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # noqa: F401 — registers all models
from db.base_class import Base
from db.models.runs import Runs
from db.models.run_directories import RunDirectories
from db.models.run_files import RunFiles
from db.models.runs_status_history import RunsStatusHistory
from services import reopen, dir_stability as ds
from services.watcher import is_completed

T0 = datetime(2026, 10, 22, 12, 0, 0)
NOW = datetime(2026, 10, 25, 12, 0, 0)


def write(path, data: bytes = b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def record(db, run, folder, rel):
    st = os.stat(folder / rel)
    db.add(RunFiles(run_uuid=run.uuid, rel_path=rel, size=st.st_size, mtime_ns=st.st_mtime_ns, sha256="a" * 64, uploaded=True))
    db.commit()


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Runs.__table__, RunFiles.__table__, RunsStatusHistory.__table__, RunDirectories.__table__])
    db = sessionmaker(bind=engine)()
    sequencer = SimpleNamespace(uuid=uuid4(), location=str(tmp_path), exclusions=[], sent_to_tre="auto",
                                type=SimpleNamespace(completion_method="signal", completion_signal="_complete.txt", signal_match="suffix",
                                                     dir_stability_minutes=10, run_stability_minutes=60))
    run = Runs(name="PROJECT_1", sequencer_uuid=sequencer.uuid, status="completed", checksum_file="old.CHECKSUM")
    db.add(run)
    db.commit()
    folder = tmp_path / "PROJECT_1"
    write(folder / "SAMPLE_1" / "reads.fastq")
    write(folder / "old.CHECKSUM")
    record(db, run, folder, "SAMPLE_1/reads.fastq")
    published = []
    publish = lambda event, name, seq_uuid, **extra: published.append((event, extra.get("directory")))
    yield SimpleNamespace(db=db, seq=sequencer, run=run, folder=folder, published=published, publish=publish)
    db.close()


def check(env):
    return reopen.process_completed_run(env.run, env.seq, env.db)


def test_nothing_new_leaves_run_completed(env):
    assert check(env) is False
    assert env.run.status == "completed"


def test_new_sample_reopens_at_once(env):
    write(env.folder / "SAMPLE_2" / "reads.fastq", b"new data")

    assert check(env) is True
    assert env.run.status == "running"
    assert env.run.checksum_file is None    # the worker writes a new .CHECKSUM
    assert env.published == []              # completion is left to the instrument's own rule
    entry = env.db.query(RunsStatusHistory).filter_by(run_uuid=env.run.uuid).one()
    assert entry.status == "running" and "SAMPLE_2/reads.fastq" in entry.detail


def test_modified_or_deleted_sent_files_do_not_reopen(env):
    write(env.folder / "SAMPLE_1" / "reads.fastq", b"changed after sending")
    assert check(env) is False
    os.remove(env.folder / "SAMPLE_1" / "reads.fastq")
    assert check(env) is False
    assert env.run.status == "completed"


def test_run_without_recorded_files_is_skipped(env):
    env.db.query(RunFiles).delete()
    env.db.commit()
    write(env.folder / "SAMPLE_2" / "a.fastq")
    assert check(env) is False and env.run.status == "completed"


def test_missing_folder_is_skipped(env, tmp_path):
    env.seq.location = str(tmp_path / "gone")
    assert check(env) is False


def test_checksum_files_and_exclusions_are_not_new_data(env):
    env.seq.exclusions = ["*.png"]
    write(env.folder / "other.CHECKSUM")
    write(env.folder / "SAMPLE_1" / "thumb.png")
    write(env.folder / ".hidden")
    assert check(env) is False


# ── completion rules after a reopen ───────────────────────────────────────────

def set_mtime(path, when: datetime):
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def finish(env, when):
    """The run reached running_finished at `when` (history entry the signal check compares against)."""
    env.db.add(RunsStatusHistory(run_uuid=env.run.uuid, status="running_finished", created_at=when))
    env.db.commit()


def test_signal_older_than_last_completion_is_ignored(env):
    write(env.folder / "RTA_complete.txt")
    set_mtime(env.folder / "RTA_complete.txt", T0)
    finish(env, T0 + timedelta(minutes=5))
    since = reopen.last_completion_time(env.run.uuid, env.db)

    assert is_completed(str(env.folder), env.seq) is True          # a first-time run: any signal counts
    assert is_completed(str(env.folder), env.seq, since) is False  # reopened: the old one is stale


def test_signal_written_after_reopen_completes_the_run(env):
    write(env.folder / "RTA_complete.txt")
    set_mtime(env.folder / "RTA_complete.txt", T0)
    finish(env, T0 + timedelta(minutes=5))
    since = reopen.last_completion_time(env.run.uuid, env.db)

    set_mtime(env.folder / "RTA_complete.txt", T0 + timedelta(days=1))   # instrument rewrote it
    assert is_completed(str(env.folder), env.seq, since) is True

    write(env.folder / "SAMPLE_2_complete.txt")                          # or wrote a new one
    set_mtime(env.folder / "RTA_complete.txt", T0)
    set_mtime(env.folder / "SAMPLE_2_complete.txt", T0 + timedelta(days=1))
    assert is_completed(str(env.folder), env.seq, since) is True


def test_last_completion_time_is_the_latest(env):
    assert reopen.last_completion_time(env.run.uuid, env.db) is None
    finish(env, T0)
    finish(env, T0 + timedelta(days=2))
    assert reopen.last_completion_time(env.run.uuid, env.db) == T0 + timedelta(days=2)


def test_directory_stability_sends_new_directory_early_after_reopen(env):
    env.seq.type = SimpleNamespace(completion_method="directory_stability", dir_stability_minutes=10, run_stability_minutes=60)
    # the first transfer: SAMPLE_1 was sent
    ds.process_run(env.run, env.seq, env.db, env.publish, now=NOW - timedelta(days=1))
    row = env.db.query(RunDirectories).one()
    row.state = ds.SENT
    env.db.commit()
    env.run.last_change_at = None

    write(env.folder / "SAMPLE_2" / "reads.fastq", b"new data")
    assert check(env) is True
    assert env.run.status == "running"

    ds.process_run(env.run, env.seq, env.db, env.publish, now=NOW)
    assert env.published == []                                   # SAMPLE_2 only just appeared
    ds.process_run(env.run, env.seq, env.db, env.publish, now=NOW + timedelta(minutes=10))
    assert env.published == [("run_directory_upload_requested", "SAMPLE_2")]   # sent early, not at the end
    states = {d.name: d.state for d in env.db.query(RunDirectories).all()}
    assert states == {"SAMPLE_1": ds.SENT, "SAMPLE_2": ds.QUEUED}
