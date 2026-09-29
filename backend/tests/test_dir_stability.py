"""
Tests for the directory stability completion method (services/dir_stability.py).

Run inside the backend container:
    docker exec fastapi_gateway_backend python -m pytest tests -q
"""
import os
import sys
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
from services import dir_stability as ds
from services.checksum import create_checksum_file

T0 = datetime(2026, 9, 29, 12, 0, 0)


def write(path, data: bytes = b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def touch_later(path, seconds=10):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 1_000_000_000))


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_scan_tree_relative_paths_and_exclusions(tmp_path):
    write(tmp_path / "DIR1" / "a.pod5")
    write(tmp_path / "DIR1" / "sub" / "b.pod5", b"yy")
    write(tmp_path / "DIR1" / "thumb.png")
    write(tmp_path / "DIR1" / ".DS_Store")
    write(tmp_path / "abc.CHECKSUM")
    write(tmp_path / "RunInfo.xml")

    listing = ds.scan_tree(str(tmp_path), exclusions=["*.png"])

    assert set(listing) == {"DIR1/a.pod5", "DIR1/sub/b.pod5", "RunInfo.xml"}
    assert listing["DIR1/sub/b.pod5"][0] == 2


def test_scan_tree_prefix_matches_run_relative_paths(tmp_path):
    write(tmp_path / "DIR1" / "sub" / "b.pod5")
    whole = ds.scan_tree(str(tmp_path), [])
    one   = ds.scan_tree(str(tmp_path / "DIR1"), [], prefix="DIR1")
    assert one == whole


def test_split_top_level():
    dirs, root = ds.split_top_level({"A/x": (1, 1), "A/b/y": (1, 1), "B/z": (1, 1), "root.txt": (1, 1)})
    assert set(dirs) == {"A", "B"}
    assert set(dirs["A"]) == {"A/x", "A/b/y"}
    assert set(root) == {"root.txt"}


def test_fingerprint_is_order_independent_and_sensitive():
    a = {"x": (1, 10), "y": (2, 20)}
    b = {"y": (2, 20), "x": (1, 10)}
    assert ds.fingerprint(a) == ds.fingerprint(b)
    assert ds.fingerprint(a) != ds.fingerprint({"x": (1, 11), "y": (2, 20)})
    assert ds.fingerprint(a) != ds.fingerprint({**a, "z": (0, 0)})


def test_diff_uploaded_ignores_new_files():
    uploaded = {"D/a": (1, 1), "D/b": (2, 2), "D/c": (3, 3)}
    current  = {"D/a": (1, 1), "D/b": (2, 9), "D/new": (5, 5)}
    modified, deleted = ds.diff_uploaded(current, uploaded)
    assert modified == ["D/b"]
    assert deleted == ["D/c"]


def test_checksum_reuses_known_digests(tmp_path):
    run = tmp_path / "RUN"
    write(run / "DIR1" / "a", b"hello")
    write(run / "root.txt", b"root")
    fresh = create_checksum_file("RUN", str(tmp_path))
    fresh_body = open(fresh).read()
    os.remove(fresh)

    st = os.stat(run / "DIR1" / "a")
    # a wrong digest proves the stored value was used instead of re-hashing
    known = {"DIR1/a": (st.st_size, st.st_mtime_ns, "f" * 64)}
    reused = open(create_checksum_file("RUN", str(tmp_path), known_digests=known)).read()
    assert "f" * 64 in reused and reused != fresh_body


def test_checksum_rehashes_changed_file(tmp_path):
    run = tmp_path / "RUN"
    write(run / "DIR1" / "a", b"hello")
    st = os.stat(run / "DIR1" / "a")
    known = {"DIR1/a": (st.st_size, st.st_mtime_ns - 1, "f" * 64)}  # stale mtime
    body = open(create_checksum_file("RUN", str(tmp_path), known_digests=known)).read()
    assert "f" * 64 not in body


# ── process_run ───────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        Runs.__table__, RunDirectories.__table__, RunFiles.__table__, RunsStatusHistory.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def env(tmp_path, db):
    sequencer = SimpleNamespace(
        uuid=uuid4(), location=str(tmp_path), sent_to_tre="auto", exclusions=[],
        type=SimpleNamespace(completion_method="directory_stability", dir_stability_minutes=10, run_stability_minutes=60),
    )
    run = Runs(name="RUN_009", sequencer_uuid=sequencer.uuid, status="running")
    db.add(run)
    db.commit()
    published = []
    publish = lambda event, name, seq_uuid, **extra: published.append((event, extra.get("directory")))
    return SimpleNamespace(seq=sequencer, run=run, db=db, published=published, publish=publish,
                           folder=tmp_path / "RUN_009")


def tick(env, minutes):
    ds.process_run(env.run, env.seq, env.db, env.publish, now=T0 + timedelta(minutes=minutes))


def dirs(env):
    return {d.name: d for d in env.db.query(RunDirectories).all()}


def mark_sent(env, name):
    """Simulate a successful worker upload of every file currently in `name`."""
    for rel, (size, mtime_ns) in ds.scan_tree(str(env.folder / name), [], prefix=name).items():
        env.db.add(RunFiles(run_uuid=env.run.uuid, rel_path=rel, size=size, mtime_ns=mtime_ns, sha256="0" * 64, uploaded=True))
    dirs(env)[name].state = ds.SENT
    env.db.commit()


def test_directory_queued_after_quiet_period(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    assert dirs(env)["DIR1"].state == ds.WAITING
    tick(env, 9)
    assert env.published == []
    tick(env, 10)
    assert dirs(env)["DIR1"].state == ds.QUEUED
    assert env.published == [("run_directory_upload_requested", "DIR1")]
    tick(env, 11)  # no duplicate publish while queued
    assert len(env.published) == 1


def test_change_resets_directory_timer(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    write(env.folder / "DIR1" / "b")
    tick(env, 8)
    tick(env, 17)
    assert dirs(env)["DIR1"].state == ds.WAITING
    tick(env, 18)
    assert dirs(env)["DIR1"].state == ds.QUEUED


def test_manual_instrument_never_sends_directories_early(env):
    env.seq.sent_to_tre = "manual"
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 30)
    assert dirs(env)["DIR1"].state == ds.WAITING
    tick(env, 60)
    assert env.published == [("run_completed", None)]


def test_run_completes_after_run_quiet_period(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 10)
    mark_sent(env, "DIR1")
    tick(env, 59)
    assert ("run_completed", None) not in env.published
    tick(env, 60)
    assert env.published[-1] == ("run_completed", None)


def test_run_waits_for_directory_uploads_in_progress(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 10)                      # queued, worker has not picked it up
    tick(env, 70)
    assert ("run_completed", None) not in env.published


def test_root_file_change_delays_run_completion(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 10)
    mark_sent(env, "DIR1")
    write(env.folder / "RunInfo.xml")
    tick(env, 30)
    tick(env, 89)
    assert ("run_completed", None) not in env.published
    tick(env, 90)
    assert env.published[-1] == ("run_completed", None)


def test_new_file_in_sent_directory_is_not_a_conflict(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 10)
    mark_sent(env, "DIR1")
    write(env.folder / "DIR1" / "late")
    tick(env, 20)
    assert dirs(env)["DIR1"].state == ds.WAITING
    assert env.run.status == "running"
    tick(env, 30)
    assert dirs(env)["DIR1"].state == ds.QUEUED


def test_modified_file_after_send_is_a_conflict(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 10)
    mark_sent(env, "DIR1")
    touch_later(env.folder / "DIR1" / "a")
    tick(env, 20)
    assert dirs(env)["DIR1"].state == ds.CONFLICT
    assert env.run.status == ds.RUN_CONFLICT_STATUS
    history = env.db.query(RunsStatusHistory).all()
    assert history[-1].status == ds.RUN_CONFLICT_STATUS
    assert "DIR1/a" in history[-1].detail


def test_deleted_file_after_send_is_a_conflict(env):
    write(env.folder / "DIR1" / "a")
    write(env.folder / "DIR1" / "b")
    tick(env, 0)
    tick(env, 10)
    mark_sent(env, "DIR1")
    os.remove(env.folder / "DIR1" / "b")
    tick(env, 20)
    assert dirs(env)["DIR1"].state == ds.CONFLICT
    assert "Deleted (1): DIR1/b" in dirs(env)["DIR1"].detail


def test_removed_sent_directory_is_a_conflict(env):
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    tick(env, 10)
    mark_sent(env, "DIR1")
    os.remove(env.folder / "DIR1" / "a")
    os.rmdir(env.folder / "DIR1")
    tick(env, 20)
    assert dirs(env)["DIR1"].state == ds.CONFLICT
    assert env.run.status == ds.RUN_CONFLICT_STATUS


def test_state_survives_a_new_session(env):
    """Timers are in the DB: a watcher restart (new session, same rows) keeps counting."""
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    env.db.expire_all()
    tick(env, 10)
    assert dirs(env)["DIR1"].state == ds.QUEUED


def test_excluded_directory_is_not_tracked(env):
    env.seq.exclusions = ["Thumbnail_Images"]
    write(env.folder / "Thumbnail_Images" / "t.jpg")
    write(env.folder / "DIR1" / "a")
    tick(env, 0)
    assert set(dirs(env)) == {"DIR1"}
