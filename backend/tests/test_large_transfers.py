"""
Behaviour that matters for terabyte-sized runs:
  - digests are recorded, so a retry neither re-hashes nor re-uploads unchanged files
  - progress is written to the DB at most every few seconds
  - the TRE wait grows with run size
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
from db.models.run_files import RunFiles
from db.models.runs_status_history import RunsStatusHistory
from services import worker, tre
from services.checksum import create_checksum_file

T0 = datetime(2026, 9, 29, 12, 0, 0)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    for t in (Runs, RunFiles, RunsStatusHistory):
        t.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(worker, "get_setting_int", lambda key, default: default)
    yield session
    session.close()


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def files(db, run_uuid):
    return {f.rel_path: f for f in db.query(RunFiles).filter(RunFiles.run_uuid == run_uuid).all()}


# ── digests & resume ──────────────────────────────────────────────────────────

def test_checksum_reports_digest_with_size_and_mtime(tmp_path):
    write(tmp_path / "RUN" / "sub" / "a.bin", b"hello")
    seen = {}
    create_checksum_file("RUN", str(tmp_path), on_digest=lambda rel, size, mtime, sha: seen.__setitem__(rel, (size, mtime, sha)))
    st = os.stat(tmp_path / "RUN" / "sub" / "a.bin")
    assert seen["sub/a.bin"][:2] == (5, st.st_mtime_ns)
    assert len(seen["sub/a.bin"][2]) == 64


def test_record_digests_keeps_uploaded_flag_only_for_unchanged_files(db):
    run = uuid4()
    worker.record_digests(run, {"a": (1, 10, "h1"), "b": (2, 20, "h2")}, db)
    worker.mark_uploaded(run, "a", db)
    worker.mark_uploaded(run, "b", db)

    worker.record_digests(run, {"a": (1, 10, "h1"), "b": (2, 21, "h2b"), "c": (3, 30, "h3")}, db)
    f = files(db, run)
    assert f["a"].uploaded is True          # unchanged → stays sent
    assert f["b"].uploaded is False         # changed → must be sent again
    assert f["c"].uploaded is False         # new


def test_mark_uploaded_ignores_unknown_paths(db):
    worker.mark_uploaded(uuid4(), "abc.CHECKSUM", db)  # no row, no error


def test_send_to_tre_skips_files_already_sent(tmp_path, monkeypatch):
    run = tmp_path / "RUN"
    write(run / "done.bin", b"old")
    write(run / "changed.bin", b"old")
    write(run / "new.bin", b"new")
    write(run / "x.CHECKSUM", b"")
    st_done, st_changed = os.stat(run / "done.bin"), os.stat(run / "changed.bin")
    already = {
        "done.bin":    (st_done.st_size, st_done.st_mtime_ns),
        "changed.bin": (st_changed.st_size, st_changed.st_mtime_ns - 1),   # stale → resend
    }
    sent, done_cb = [], []
    monkeypatch.setattr(tre, "_check_endpoint", lambda: None)
    monkeypatch.setattr(tre, "upload_file_list",
                        lambda lst, slug, on_progress=None, on_file_done=None: (sent.extend(r for _, r in lst),
                                                                                [on_file_done(lp, rp) for lp, rp in lst]))
    tre.send_to_tre("RUN", str(tmp_path), "slug", already_uploaded=already, on_file_done=lambda lp, rp: done_cb.append(rp))

    assert "RUN/done.bin" not in sent
    assert {"RUN/changed.bin", "RUN/new.bin", "RUN/x.CHECKSUM"} == set(sent)
    assert sent[-1] == "RUN/x.CHECKSUM"      # TRE trigger still last
    assert done_cb == sent


# ── progress throttling ───────────────────────────────────────────────────────

def test_progress_is_throttled_but_final_update_always_written(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    writes = []
    cb = worker._throttled(lambda *a: writes.append(a), min_interval=2.0)

    cb(0, 1, 0, 1000)                      # first → written
    for b in range(1, 500):                # thousands of chunk callbacks within one second
        cb(0, 1, b, 1000)
    clock[0] += 0.5
    cb(0, 1, 600, 1000)
    assert len(writes) == 1
    clock[0] += 2.0
    cb(0, 1, 700, 1000)                    # interval passed → written
    cb(1, 1, 1000, 1000)                   # final → written even inside the interval
    assert [w[2] for w in writes] == [0, 700, 1000]


# ── TRE wait scales with run size ─────────────────────────────────────────────

def verifying_run(db, total_bytes):
    run = Runs(name="BIG", sequencer_uuid=uuid4(), status="verifying", checksum_file="x.CHECKSUM")
    db.add(run)
    db.commit()
    db.add(RunsStatusHistory(run_uuid=run.uuid, status="verifying", created_at=T0))
    db.add(RunFiles(run_uuid=run.uuid, rel_path="data.bin", size=total_bytes, mtime_ns=1, sha256="0" * 64))
    db.commit()
    return run


@pytest.mark.parametrize("size, still_waiting_at, failed_at", [
    (1e6,    59,  60),     # small run: the 1 h base
    (250e9,  119, 120),    # 250 GB: 60 + 2.5 × 24
    (1.0e12, 299, 300),    # 1 TB:   60 + 10 × 24
])
def test_tre_wait_grows_with_run_size(db, monkeypatch, size, still_waiting_at, failed_at):
    monkeypatch.setattr(worker, "check_verify_status", lambda name: {"status": "pending"})
    run = verifying_run(db, size)
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=still_waiting_at))
    assert run.status == "verifying"
    worker.check_verifying_run(run, db, now=T0 + timedelta(minutes=failed_at))
    assert run.status == "verify_failed"
    assert f"within {failed_at} min" in db.query(RunsStatusHistory).order_by(RunsStatusHistory.id.desc()).first().detail
