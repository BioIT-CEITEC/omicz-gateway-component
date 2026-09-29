"""
One-click update: git behaviour against real temporary repositories, and the
endpoint's decisions (active transfers, migrations, restarts) with Docker stubbed.

Run inside the frontend container:
    docker exec -w /app fastapi_gateway_frontend python -m pytest tests -q
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater

COMPOSE_V1 = """services:
  db:
    ports:
      - "5432:5432"
  worker:
    volumes:
      - ./backend:/app
      - ${MACHINE_1_PATH}:/runs/machine-1
"""


def sh(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


@pytest.fixture
def repos(tmp_path):
    """origin (bare) ← upstream (where 'releases' are committed) and site (the installed copy)."""
    origin, upstream, site = tmp_path / "origin.git", tmp_path / "upstream", tmp_path / "site"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(upstream)], check=True, capture_output=True)
    sh(upstream, "checkout", "-q", "-b", "main")
    write(upstream / "docker-compose.yml", COMPOSE_V1)
    write(upstream / "VERSION", "1.1.17\n")
    sh(upstream, "add", ".")
    sh(upstream, "commit", "-q", "-m", "v1.1.17")
    sh(upstream, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(site)], check=True, capture_output=True)
    return upstream, site


def release(upstream, compose=None, version="1.2.0", extra=None):
    if compose is not None:
        write(upstream / "docker-compose.yml", compose)
    write(upstream / "VERSION", version + "\n")
    for name, text in (extra or {}).items():
        os.makedirs(os.path.dirname(upstream / name), exist_ok=True)
        write(upstream / name, text)
    sh(upstream, "add", ".")
    sh(upstream, "commit", "-q", "-m", f"v{version}")
    sh(upstream, "push", "-q", "origin", "main")


def read(path):
    return open(path).read()


def stash_list(site):
    return subprocess.run(["git", "stash", "list"], cwd=site, capture_output=True, text=True).stdout


# ── git behaviour ─────────────────────────────────────────────────────────────

def test_clean_site_updates(repos):
    upstream, site = repos
    release(upstream, extra={"backend/alembic/versions/x1_new.py": "# migration\n"})
    r = updater.pull_keeping_local_changes(str(site))
    assert r["ok"]
    assert read(site / "VERSION") == "1.2.0\n"
    assert "backend/alembic/versions/x1_new.py" in r["changed_files"]
    assert r["log"] == []


def test_site_with_edited_compose_updates_and_keeps_its_lines(repos):
    """The v1.2.0 case: site added an instrument volume, the release changed the db port line."""
    upstream, site = repos
    local = COMPOSE_V1.replace("      - ${MACHINE_1_PATH}:/runs/machine-1\n",
                               "      - ${MACHINE_1_PATH}:/runs/machine-1\n      - ${MACHINE_2_PATH}:/runs/machine-2\n")
    write(site / "docker-compose.yml", local)
    release(upstream, compose=COMPOSE_V1.replace('"5432:5432"', '"${DB_HOST_PORT:-5432}:5432"'))

    r = updater.pull_keeping_local_changes(str(site))

    assert r["ok"], r["error"]
    compose = read(site / "docker-compose.yml")
    assert "/runs/machine-2" in compose                       # site's edit kept
    assert "${DB_HOST_PORT:-5432}" in compose                 # release applied
    assert read(site / "VERSION") == "1.2.0\n"
    assert "docker-compose.yml" in r["changed_files"]
    assert stash_list(site) == ""                              # no leftover stash
    assert any("re-applied" in line for line in r["log"])


def test_overlapping_edit_rolls_back_with_local_change_kept(repos):
    upstream, site = repos
    write(site / "docker-compose.yml", COMPOSE_V1.replace('"5432:5432"', '"5544:5432"'))  # site changed the port
    release(upstream, compose=COMPOSE_V1.replace('"5432:5432"', '"${DB_HOST_PORT:-5432}:5432"'))
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=site, capture_output=True, text=True).stdout

    r = updater.pull_keeping_local_changes(str(site))

    assert not r["ok"]
    assert "NOT applied" in r["error"] and "docker-compose.override.yml" in r["error"]
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=site, capture_output=True, text=True).stdout == before
    assert read(site / "VERSION") == "1.1.17\n"                # still the old version
    assert '"5544:5432"' in read(site / "docker-compose.yml")  # local change intact
    assert "<<<<<<<" not in read(site / "docker-compose.yml")  # no conflict markers
    assert stash_list(site) == ""


def test_failed_pull_restores_local_changes(repos):
    upstream, site = repos
    write(site / "docker-compose.yml", COMPOSE_V1 + "# local note\n")
    sh(site, "commit", "-q", "-am", "local commit")            # diverged history → --ff-only fails
    write(site / "VERSION", "1.1.17-site\n")                    # plus an uncommitted edit
    release(upstream)

    r = updater.pull_keeping_local_changes(str(site))

    assert not r["ok"]
    assert read(site / "VERSION") == "1.1.17-site\n"
    assert stash_list(site) == ""


def test_untracked_site_files_are_not_touched(repos):
    upstream, site = repos
    write(site / "docker-compose.override.yml", "services: {}\n")   # git-ignored at real sites
    write(site / ".env", "MACHINE_1_PATH=/data\n")
    release(upstream)
    r = updater.pull_keeping_local_changes(str(site))
    assert r["ok"] and r["log"] == []
    assert read(site / "docker-compose.override.yml") == "services: {}\n"
    assert read(site / ".env") == "MACHINE_1_PATH=/data\n"


def test_already_up_to_date(repos):
    _, site = repos
    r = updater.pull_keeping_local_changes(str(site))
    assert r["ok"] and r["changed_files"] == []


# ── endpoint decisions ────────────────────────────────────────────────────────

class FakeContainer:
    def __init__(self, name, restarted):
        self.name, self._restarted = name, restarted

    def restart(self):
        self._restarted.append(self.name)


@pytest.fixture
def system(monkeypatch, tmp_path):
    from routers import system as sysmod
    restarted = []
    fake_docker = type("D", (), {"containers": type("C", (), {"get": staticmethod(lambda n: FakeContainer(n, restarted))})()})()
    monkeypatch.setattr(sysmod, "WORKSPACE", str(tmp_path))
    monkeypatch.setattr(sysmod.docker, "from_env", lambda: fake_docker)
    monkeypatch.setattr(sysmod.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(sysmod.subprocess, "run", lambda *a, **k: None)
    sysmod._restarted = restarted
    return sysmod


def pulled(changed):
    return lambda ws: {"ok": True, "output": "Fast-forward", "log": [], "changed_files": changed}


def body(resp):
    return resp.status_code, json.loads(resp.body)


def test_asks_before_interrupting_transfers(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers",
                        lambda: {"count": 1, "runs": [{"name": "RUN_1", "status": "moving"}], "directories": []})
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes", lambda ws: pytest.fail("must not pull"))
    code, data = body(system.do_update(force=False))
    assert code == 409 and data["busy"] and "RUN_1 (moving)" in data["error"]


def test_force_updates_despite_transfers(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers", lambda: pytest.fail("force skips the check"))
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes", pulled(["VERSION"]))
    monkeypatch.setattr(system, "_run_migrations", lambda: (True, ""))
    code, data = body(system.do_update(force=True))
    assert code == 200 and data["success"]


def test_migrations_always_run_and_services_restart(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers", lambda: {"count": 0})
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes", pulled(["frontend/routers/x.py"]))  # no migration file
    ran = []
    monkeypatch.setattr(system, "_run_migrations", lambda: (ran.append(1), (True, "Running upgrade"))[1])
    code, data = body(system.do_update(force=False))
    assert ran == [1]
    assert system._restarted == ["fastapi_gateway_watcher", "fastapi_gateway_worker", "fastapi_gateway_backend"]
    assert data["warnings"] == []


def test_failed_migration_keeps_worker_on_old_version(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers", lambda: {"count": 0})
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes", pulled(["backend/alembic/versions/x.py"]))
    monkeypatch.setattr(system, "_run_migrations", lambda: (False, "sqlalchemy error"))
    code, data = body(system.do_update(force=False))
    assert data["success"] and system._restarted == []
    assert "migration FAILED" in data["warnings"][0]


def test_nothing_to_update_restarts_nothing(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers", lambda: {"count": 0})
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes", pulled([]))
    monkeypatch.setattr(system, "_run_migrations", lambda: pytest.fail("no migration when nothing changed"))
    code, data = body(system.do_update(force=False))
    assert data["success"] and system._restarted == []


def test_compose_change_is_reported(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers", lambda: {"count": 0})
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes", pulled(["docker-compose.yml", "backend/requirements.txt"]))
    monkeypatch.setattr(system, "_run_migrations", lambda: (True, ""))
    code, data = body(system.do_update(force=False))
    assert data["needs_compose_up"] and data["needs_rebuild"]
    assert any("docker compose up -d" in w for w in data["warnings"])


def test_failed_pull_is_reported_without_restarts(system, monkeypatch):
    monkeypatch.setattr(system, "_active_transfers", lambda: {"count": 0})
    monkeypatch.setattr(system.updater, "pull_keeping_local_changes",
                        lambda ws: {"ok": False, "error": "The update was NOT applied", "log": ["Local changes restored."]})
    code, data = body(system.do_update(force=False))
    assert code == 500 and "NOT applied" in data["error"] and system._restarted == []
