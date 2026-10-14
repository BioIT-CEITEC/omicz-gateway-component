"""
Directory stability upload: files are hashed in a few threads and each one is sent as soon as
it is hashed, so the network does not wait for the whole directory. Progress shows both.
"""
import hashlib
import os
import sys
import threading
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
from services import checksum, dir_stability, worker
from services.checksum import HashQueue, HashingAborted


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── HashQueue ─────────────────────────────────────────────────────────────────

def test_hash_queue_gives_each_files_digest(tmp_path):
    data  = {f"f{i}": os.urandom(1000 + i) for i in range(6)}
    paths = []
    for name, content in data.items():
        (tmp_path / name).write_bytes(content)
        paths.append(str(tmp_path / name))
    read = []
    q = HashQueue(paths, on_bytes=read.append)
    assert [q.wait(p) for p in paths] == [sha(c) for c in data.values()]
    assert sum(read) == sum(len(c) for c in data.values())


def test_hash_queue_raises_the_files_own_error(tmp_path):
    (tmp_path / "ok").write_bytes(b"ok")
    q = HashQueue([str(tmp_path / "ok"), str(tmp_path / "gone")])
    assert q.wait(str(tmp_path / "ok")) == sha(b"ok")
    with pytest.raises(FileNotFoundError):
        q.wait(str(tmp_path / "gone"))


def test_abort_skips_files_not_hashed_yet(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).write_bytes(name.encode())
    reading, release = threading.Event(), threading.Event()

    def on_bytes(n):
        reading.set()
        release.wait(5)

    q = HashQueue([str(tmp_path / "a"), str(tmp_path / "b")], on_bytes=on_bytes, max_workers=1)
    assert reading.wait(5)                  # "a" is being read
    q.abort()
    release.set()
    q.wait(str(tmp_path / "a"))             # already read to the end: finishes or stops, never hangs
    with pytest.raises(HashingAborted):
        q.wait(str(tmp_path / "b"))


# ── worker ────────────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    # a file database: progress is written from the hashing threads, each with its own connection
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(engine, tables=[
        Runs.__table__, RunDirectories.__table__, RunFiles.__table__, RunsStatusHistory.__table__,
    ])
    make = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, "SESSION_LOCAL", make)
    monkeypatch.setattr(checksum, "_chunk_size", lambda: 64 * 1024)
    seq = SimpleNamespace(uuid=uuid4(), location=str(tmp_path / "seq"), slug="m1", exclusions=[])
    monkeypatch.setattr(worker, "get_sequencer", lambda uuid: seq)
    db = make()
    run = Runs(name="RUN", sequencer_uuid=seq.uuid, status="running")
    db.add(run)
    db.commit()
    row = RunDirectories(run_uuid=run.uuid, name="DIR1", state=dir_stability.QUEUED)
    db.add(row)
    db.commit()
    files = {"DIR1/a.pod5": os.urandom(300_000), "DIR1/sub/b.pod5": os.urandom(200_000), "DIR1/c.txt": b"c"}
    for rel, content in files.items():
        path = tmp_path / "seq" / "RUN" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    yield SimpleNamespace(db=db, seq=seq, run=run, row=row, files=files)
    db.close()


def upload_dir(env):
    worker.handle_run_directory_upload_requested("RUN", env.seq.uuid, "DIR1")
    env.db.expire_all()
    return env.db.query(RunDirectories).filter_by(uuid=env.row.uuid).one()


def test_each_file_is_sent_once_hashed_and_its_digest_recorded(env, monkeypatch):
    sent = []

    def upload_file_list(upload_files, slug, on_progress, on_file_done, ready):
        for lp, rp in upload_files:
            ready(lp)                                   # what both engines do before a file
            sent.append(rp)
            on_file_done(lp, rp)

    monkeypatch.setattr(worker, "upload_file_list", upload_file_list)
    row = upload_dir(env)

    assert row.state == dir_stability.SENT and row.detail is None
    assert sorted(sent) == sorted(f"RUN/{rel}" for rel in env.files)
    recorded = {f.rel_path: (f.sha256, f.uploaded) for f in env.db.query(RunFiles).all()}
    assert recorded == {rel: (sha(c), True) for rel, c in env.files.items()}


def test_a_file_that_cannot_be_hashed_fails_the_directory(env, monkeypatch):
    scan = dir_stability.scan_tree
    monkeypatch.setattr(dir_stability, "scan_tree",
                        lambda *a, **kw: {**scan(*a, **kw), "DIR1/vanished.pod5": (10, 1)})
    sent = []

    def upload_file_list(upload_files, slug, on_progress, on_file_done, ready):
        for lp, rp in upload_files:
            ready(lp)
            sent.append(rp)
            on_file_done(lp, rp)

    monkeypatch.setattr(worker, "upload_file_list", upload_file_list)
    row = upload_dir(env)

    assert row.state == dir_stability.FAILED
    assert "vanished.pod5" in row.detail
    assert "RUN/DIR1/vanished.pod5" not in sent


def test_progress_shows_hashing_until_everything_is_hashed(env, monkeypatch):
    monkeypatch.setattr(worker, "PROGRESS_MIN_INTERVAL", 0)

    def progress_text():
        env.db.expire_all()
        return env.db.query(RunDirectories).filter_by(uuid=env.row.uuid).one().progress

    p = worker._DirProgress(env.row.uuid, 2, 2048)
    p.hashed(1024)
    assert progress_text() == "hashing 1.0 KB / 2.0 KB · 0 / 2 files · 0.0 B / 2.0 KB"
    p.upload(1, 2, 1024, 2048)
    assert progress_text() == "hashing 1.0 KB / 2.0 KB · 1 / 2 files · 1.0 KB / 2.0 KB"
    p.hashed(1024)
    assert progress_text() == "1 / 2 files · 1.0 KB / 2.0 KB"
