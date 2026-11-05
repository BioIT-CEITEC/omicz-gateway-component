"""
CHECKSUM_DIR: the manifest is written outside the run folder, so the instrument folders can be
mounted read-only, and it is still uploaded last under <run name>/<hash>.CHECKSUM.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import checksum, tre
from services.checksum import create_checksum_file, find_manifest, manifest_dir, remove_manifests


def write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def layout(tmp_path, monkeypatch):
    seq = tmp_path / "runs" / "m1"
    run = seq / "RUN"
    write(run / "Data" / "a.bin", b"a")
    write(run / "b.txt", b"b")
    out = tmp_path / "checksums"
    monkeypatch.setattr(checksum, "CHECKSUM_DIR", str(out))
    return seq, run, out


def test_manifest_dir_follows_checksum_dir(layout, monkeypatch):
    seq, run, out = layout
    assert manifest_dir(str(seq), "m1", "RUN") == str(out / "m1" / "RUN")
    monkeypatch.setattr(checksum, "CHECKSUM_DIR", None)
    assert manifest_dir(str(seq), "m1", "RUN") == str(run)


def test_manifest_is_written_outside_the_run_folder(layout):
    seq, run, out = layout
    before = sorted(p.name for p in run.rglob("*"))
    path = create_checksum_file("RUN", str(seq), out_dir=manifest_dir(str(seq), "m1", "RUN"))
    assert os.path.dirname(path) == str(out / "m1" / "RUN")
    assert path.endswith(".CHECKSUM")
    assert len(open(path).read().split()) == 2         # the two data files
    assert sorted(p.name for p in run.rglob("*")) == before


def test_old_manifest_in_run_folder_is_not_hashed_or_uploaded(layout, monkeypatch):
    seq, run, out = layout
    write(run / "old.CHECKSUM", b"stale")
    path = create_checksum_file("RUN", str(seq), out_dir=manifest_dir(str(seq), "m1", "RUN"))
    assert len(open(path).read().split()) == 2

    sent = []
    monkeypatch.setattr(tre, "_check_endpoint", lambda: None)
    monkeypatch.setattr(tre, "upload_file_list", lambda lst, slug, **kw: sent.extend(lst))
    tre.send_to_tre("RUN", str(seq), "m1", manifest_path=path)
    rels = [rp for _, rp in sent]
    assert "RUN/old.CHECKSUM" not in rels
    assert sent[-1] == (path, f"RUN/{os.path.basename(path)}")   # last, at the usual S3 key
    assert sorted(rels[:-1]) == ["RUN/Data/a.bin", "RUN/b.txt"]


def test_find_manifest_falls_back_to_the_run_folder(layout):
    seq, run, out = layout
    write(run / "legacy.CHECKSUM")                      # written by a version before CHECKSUM_DIR
    assert find_manifest(str(seq), "m1", "RUN", "legacy.CHECKSUM") == str(run / "legacy.CHECKSUM")
    write(out / "m1" / "RUN" / "new.CHECKSUM")
    assert find_manifest(str(seq), "m1", "RUN", "new.CHECKSUM") == str(out / "m1" / "RUN" / "new.CHECKSUM")
    assert find_manifest(str(seq), "m1", "RUN", "missing.CHECKSUM") is None


def test_remove_manifests_skips_a_read_only_run_folder(layout, monkeypatch):
    seq, run, out = layout
    write(run / "legacy.CHECKSUM")
    write(out / "m1" / "RUN" / "new.CHECKSUM")
    real_remove = os.remove

    def remove(path):                                   # the run folder is mounted :ro
        if str(path).startswith(str(run)):
            raise OSError(30, "Read-only file system")
        real_remove(path)

    monkeypatch.setattr(os, "remove", remove)
    remove_manifests(str(seq), "m1", "RUN")             # no error
    assert not (out / "m1" / "RUN" / "new.CHECKSUM").exists()
    assert (run / "legacy.CHECKSUM").exists()
