"""
Reopening of completed runs.

A run is a top-level folder of the instrument location. A project folder can
get new samples or runs after it was transferred, so the watcher keeps looking
at 'completed' runs: files that are not in run_files (everything that was sent
is recorded there) are new data. The run goes back to 'running' at once, and
from there the instrument's own completion rule decides when the new data is
done, exactly as for a new run:

  signal               a matching file that is newer than the previous completion
                       (the old signal file is still in the folder and means nothing)
  file_stability       the monitored files stop growing
  directory_stability  new directories are sent early once quiet; the run is
                       finalized when the whole folder stops changing

The normal checksum → upload → verify pipeline then sends only the new files
(sent files are skipped, their digests reused) and a new .CHECKSUM that covers
the whole folder.

Changes to files that were already sent are not a reason to reopen: the S3
proxy refuses overwrites, and instruments often touch old files after the
transfer. Runs without run_files rows (transferred by a version that did not
record them) are skipped, since nothing tells new from old.
"""
import os
from datetime import datetime

from services import dir_stability
from core.logger import get_logger

logger = get_logger("reopen")

_MAX_FILES_IN_DETAIL = 10


def new_files(run, sequencer, db) -> list[str] | None:
    """
    Paths in the run folder that were never recorded as sent. None when the check cannot
    be made: folder not accessible, or the run has no run_files rows.
    """
    run_folder = os.path.join(sequencer.location, run.name)
    if not os.path.isdir(run_folder):
        return None
    known = dir_stability.known_digests(run.uuid, db)
    if not known:
        return None
    current = dir_stability.scan_tree(run_folder, sequencer.exclusions or [])
    return sorted(rel for rel in current if rel not in known)


def reopen_detail(added: list[str]) -> str:
    shown = ", ".join(added[:_MAX_FILES_IN_DETAIL]) + (" …" if len(added) > _MAX_FILES_IN_DETAIL else "")
    return f"New data found after the run was transferred ({len(added)} new file(s): {shown}). Waiting for it to finish."


def last_completion_time(run_uuid, db) -> datetime | None:
    """When the run last reached running_finished — a completion signal older than this is stale."""
    from db.models.runs_status_history import RunsStatusHistory
    row = (
        db.query(RunsStatusHistory)
        .filter(RunsStatusHistory.run_uuid == run_uuid, RunsStatusHistory.status == "running_finished")
        .order_by(RunsStatusHistory.created_at.desc())
        .first()
    )
    return row.created_at if row else None


def process_completed_run(run, sequencer, db) -> bool:
    """One watcher pass over a 'completed' run. Returns True when the run was reopened."""
    from db.repositories.runs_status_history import add_run_status_history

    added = new_files(run, sequencer, db)
    if not added:
        return False

    # the old .CHECKSUM was uploaded already; clearing the name makes the worker write a new one
    run.status               = "running"
    run.checksum_file        = None
    run.progress             = None
    run.activity_fingerprint = None   # directory stability starts its run-wide quiet timer again
    run.last_change_at       = None
    db.commit()
    add_run_status_history(run_uuid=run.uuid, status="running", db=db, detail=reopen_detail(added))
    logger.info(f"run '{run.name}' reopened: {len(added)} new file(s) after it was completed")
    return True
