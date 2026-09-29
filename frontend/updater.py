"""
Git side of the one-click update (Settings → Update).

Sites edit tracked files (e.g. docker-compose.yml to add an instrument volume).
A plain `git pull --ff-only` refuses to run when an incoming commit touches such a
file, so the update would fail at every customised site. This module:

  1. sets local changes aside (git stash),
  2. fast-forwards to the latest version,
  3. puts the local changes back (git stash apply).

If the local changes cannot be put back cleanly (the same lines were changed
upstream), it rolls back to the old version with the local changes restored, so a
site is never left half-updated or with conflict markers in its files.
"""
import os
import subprocess
import time

# stash needs a committer identity; sites often have none configured
_IDENTITY = ["-c", "user.name=OmiCZ Gateway update", "-c", "user.email=update@omicz-gateway.local"]


def _git(workspace: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *_IDENTITY, "-C", workspace, *args],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _out(result: subprocess.CompletedProcess) -> str:
    return (result.stdout + result.stderr).strip()


def local_changes(workspace: str) -> list[str]:
    """Tracked files with uncommitted local edits (untracked and ignored files are never touched)."""
    result = _git(workspace, "status", "--porcelain", "--untracked-files=no")
    return [line[3:] for line in result.stdout.splitlines() if line.strip()]


def pull_keeping_local_changes(workspace: str) -> dict:
    """
    Fast-forward the workspace to its upstream, keeping local edits.
    Returns {"ok", "error", "output", "log", "old_head", "new_head", "changed_files"}.
    """
    log: list[str] = []
    old_head = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    changed  = local_changes(workspace)

    stashed = False
    if changed:
        stash = _git(workspace, "stash", "push", "-m", f"omicz-update {time.strftime('%Y-%m-%d %H:%M:%S')}")
        if stash.returncode != 0:
            return {"ok": False, "error": f"Could not set local changes aside:\n{_out(stash)}", "log": log}
        stashed = True
        log.append("Local changes set aside during the update: " + ", ".join(changed))

    pull = _git(workspace, "pull", "--ff-only")
    if pull.returncode != 0:
        if stashed:
            _git(workspace, "stash", "pop")
            log.append("Local changes restored.")
        return {"ok": False, "error": _out(pull), "log": log, "old_head": old_head}

    new_head = _git(workspace, "rev-parse", "HEAD").stdout.strip()

    if stashed:
        apply = _git(workspace, "stash", "apply")
        if apply.returncode != 0:
            # the same lines changed upstream — go back to the old version with local edits intact
            _git(workspace, "reset", "--hard", old_head)
            _git(workspace, "stash", "pop")
            return {
                "ok": False,
                "old_head": old_head,
                "log": log,
                "error": (
                    "The update was NOT applied: your local changes to "
                    + ", ".join(changed)
                    + " overlap with changes in the new version.\n"
                    "The site is still on the previous version and your changes are kept.\n\n"
                    "To fix: move site-specific settings (e.g. instrument volumes) from docker-compose.yml "
                    "into docker-compose.override.yml (see README, 'Adding a new machine'), "
                    "restore the original file with 'git checkout docker-compose.yml', then click Update again."
                ),
            }
        _git(workspace, "stash", "drop")
        log.append("Local changes re-applied: " + ", ".join(changed))

    diff = _git(workspace, "diff", "--name-only", old_head, new_head)
    return {
        "ok": True,
        "error": None,
        "output": _out(pull),
        "log": log,
        "old_head": old_head,
        "new_head": new_head,
        "changed_files": [f for f in diff.stdout.splitlines() if f.strip()],
    }
