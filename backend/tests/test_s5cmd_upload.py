"""
s5cmd upload engine: files go in one parallel batch, the .CHECKSUM manifest after them,
failed files are sent again on their own, and each finished file is recorded at once.
A fake s5cmd on PATH plays the binary, so no network is needed.
"""
import json
import os
import stat
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import tre

FAKE_S5CMD = textwrap.dedent('''\
    #!{python}
    import json, os, shlex, sys
    args = sys.argv[1:]
    run_file = args[args.index("run") + 1]
    state_path = os.environ["FAKE_S5CMD_STATE"]
    state = json.load(open(state_path))
    batch, failed = [], False
    for line in open(run_file):
        parts = shlex.split(line)
        src, dst = parts[-2], parts[-1]
        batch.append(dst)
        fails = state["fail"].get(dst, 0)
        if fails:
            state["fail"][dst] = fails - 1
            failed = True
            print(json.dumps({{"operation": "cp", "command": "cp --raw=true " + src + " " + dst,
                              "error": state["error"]}}), file=sys.stderr)
        else:
            print(json.dumps({{"operation": "cp", "success": True, "source": src, "destination": dst}}), flush=True)
    state["batches"].append(batch)
    json.dump(state, open(state_path, "w"))
    sys.exit(1 if failed else 0)
''')


@pytest.fixture
def fake_s5cmd(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "s5cmd"
    exe.write_text(FAKE_S5CMD.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    state_path = tmp_path / "state.json"

    def configure(fail=None, error="RequestError: send request failed"):
        state_path.write_text(json.dumps({"fail": fail or {}, "error": error, "batches": []}))

    configure()
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_S5CMD_STATE", str(state_path))
    monkeypatch.setattr(tre, "S3_BUCKET", "bkt")
    monkeypatch.setattr(tre, "S3_PREFIX", "pre/")
    monkeypatch.setattr(tre, "S3_ENDPOINT", "http://s3.invalid")
    monkeypatch.setattr(tre, "_check_endpoint", lambda: None)
    monkeypatch.setattr(tre, "get_setting_str", lambda key, default: "s5cmd" if key == "upload_engine" else default)
    monkeypatch.setattr(tre, "get_setting_int", lambda key, default: default)
    monkeypatch.setattr(tre.time, "sleep", lambda s: None)
    configure.batches = lambda: json.loads(state_path.read_text())["batches"]
    return configure


@pytest.fixture
def run_files(tmp_path):
    run = tmp_path / "seq" / "RUN"
    (run / "Data").mkdir(parents=True)
    files = {"Data/a.bin": b"a" * 10, "Data/b c.bin": b"b" * 20, "x*y.txt": b"c" * 30, "abc.CHECKSUM": b"d" * 5}
    for rel, data in files.items():
        (run / rel).write_bytes(data)
    # the manifest comes last, as send_to_tre sorts it
    return [(str(run / rel), f"RUN/{rel}") for rel in files]


def dest(rel):
    return f"s3://bkt/pre/slug/{rel}"


def test_manifest_goes_after_all_data_files(fake_s5cmd, run_files):
    done, progress = [], []
    tre.upload_file_list(run_files, "slug", on_progress=lambda *a: progress.append(a),
                         on_file_done=lambda lp, rp: done.append(rp))

    batches = fake_s5cmd.batches()
    assert len(batches) == 2
    assert sorted(batches[0]) == sorted(dest(rp) for _, rp in run_files[:3])
    assert batches[1] == [dest("RUN/abc.CHECKSUM")]
    assert sorted(done) == sorted(rp for _, rp in run_files)
    assert done[-1] == "RUN/abc.CHECKSUM"
    assert progress[0] == (0, 4, 0, 65)
    assert progress[-1] == (4, 4, 65, 65)


def test_failed_file_is_sent_again_on_its_own(fake_s5cmd, run_files):
    fake_s5cmd(fail={dest("RUN/Data/b c.bin"): 2})
    done = []
    tre.upload_file_list(run_files, "slug", on_file_done=lambda lp, rp: done.append(rp))

    batches = fake_s5cmd.batches()
    assert batches[1] == [dest("RUN/Data/b c.bin")]
    assert batches[2] == [dest("RUN/Data/b c.bin")]
    assert batches[3] == [dest("RUN/abc.CHECKSUM")]
    assert sorted(done) == sorted(rp for _, rp in run_files)


def test_precondition_failed_counts_as_already_uploaded(fake_s5cmd, run_files):
    fake_s5cmd(fail={dest("RUN/x*y.txt"): 1}, error="PreconditionFailed: At least one of the pre-conditions you specified did not hold")
    done = []
    tre.upload_file_list(run_files, "slug", on_file_done=lambda lp, rp: done.append(rp))

    assert len(fake_s5cmd.batches()) == 2          # not retried
    assert "RUN/x*y.txt" in done


def test_gives_up_after_max_attempts(fake_s5cmd, run_files):
    fake_s5cmd(fail={dest("RUN/Data/a.bin"): 99})
    done = []
    with pytest.raises(RuntimeError, match="a.bin"):
        tre.upload_file_list(run_files, "slug", on_file_done=lambda lp, rp: done.append(rp))

    assert len(fake_s5cmd.batches()) == 5          # upload_max_attempts default
    assert "RUN/abc.CHECKSUM" not in done          # no manifest when a data file is missing
    assert "RUN/Data/a.bin" not in done


def test_error_in_on_file_done_stops_the_upload(fake_s5cmd, run_files):
    class Conflict(Exception):
        pass

    def on_file_done(lp, rp):
        raise Conflict(rp)

    with pytest.raises(Conflict):
        tre.upload_file_list(run_files, "slug", on_file_done=on_file_done)
    assert len(fake_s5cmd.batches()) <= 1          # manifest batch never started


def test_part_size_grows_for_files_over_10000_parts(monkeypatch):
    monkeypatch.setattr(tre.os.path, "getsize", lambda p: 1024 ** 4)   # 1 TiB
    line = tre._s5cmd_command("/runs/x/it's.bin", "bkt", "pre/it's.bin")
    assert "--part-size 105 " in line
    assert line.endswith("'/runs/x/it'\"'\"'s.bin' 's3://bkt/pre/it'\"'\"'s.bin'")


def test_missing_binary_falls_back_to_boto3(monkeypatch):
    monkeypatch.setattr(tre, "get_setting_str", lambda key, default: "s5cmd")
    monkeypatch.setattr(tre.shutil, "which", lambda name: None)
    assert tre.upload_engine() == "boto3"
