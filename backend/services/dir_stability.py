"""
Directory stability completion method.

A run folder is treated as a set of top-level directories:

    RUN_009/
        DIR1/...        ← sent on its own once quiet for dir_stability_minutes
        DIR2/...
        RunInfo.xml     ← root-level files wait for finalization

Each watcher pass scans the run folder once and fingerprints every top-level
directory from (relative path, size, mtime_ns) of the files inside it. A
directory whose fingerprint has not changed for dir_stability_minutes is
queued for upload (sent_to_tre=auto only). When the fingerprint of the whole
run has not changed for run_stability_minutes, run_completed is published and
the normal checksum → upload → verify pipeline finalizes the run, reusing the
digests of files that were already sent.

The S3 proxy refuses overwrites, so a file that is modified or deleted after
it was sent cannot be fixed by re-sending. That directory is marked
"conflict" and the run goes to "transfer_conflict" until a person acts.
New files appearing in an already-sent directory are not a conflict: the
directory goes back to "waiting" and only the new files are sent later.
"""
import hashlib
import os
from datetime import datetime, timedelta

from services.checksum import BUILTIN_EXCLUSIONS, CHECKSUM_FILENAME, _is_excluded
from core.logger import get_logger

logger = get_logger("dir_stability")

# directory states
WAITING   = "waiting"
QUEUED    = "queued"
UPLOADING = "uploading"
SENT      = "sent"
FAILED    = "failed"
CONFLICT  = "conflict"

RUN_CONFLICT_STATUS = "transfer_conflict"

_MAX_FILES_IN_DETAIL = 20


def _is_checksum_file(name: str) -> bool:
    return name == CHECKSUM_FILENAME or name.endswith(".CHECKSUM")


def scan_tree(folder: str, exclusions: list[str], prefix: str = "") -> dict[str, tuple[int, int]]:
    """
    Walk folder and return {relative_path: (size, mtime_ns)} for every file.
    Paths are "/" separated and prefixed with `prefix` (e.g. "DIR1") so they are
    relative to the run folder. Excluded files and .CHECKSUM files are skipped.
    Files that disappear between listing and stat are skipped silently.
    """
    all_exclusions = BUILTIN_EXCLUSIONS + (exclusions or [])
    listing: dict[str, tuple[int, int]] = {}
    for root, dirs, files in os.walk(folder):
        rel_root = os.path.relpath(root, folder).replace(os.sep, "/")
        rel_root = "" if rel_root == "." else rel_root
        for filename in files:
            if _is_checksum_file(filename):
                continue
            rel = f"{rel_root}/{filename}" if rel_root else filename
            if prefix:
                rel = f"{prefix}/{rel}"
            if _is_excluded(rel, all_exclusions):
                continue
            try:
                st = os.stat(os.path.join(root, filename))
            except OSError:
                continue
            listing[rel] = (st.st_size, st.st_mtime_ns)
    return listing


def split_top_level(listing: dict[str, tuple[int, int]]) -> tuple[dict[str, dict], dict[str, tuple[int, int]]]:
    """Split a run listing into ({top_dir: sub_listing}, root_files)."""
    dirs: dict[str, dict] = {}
    root_files: dict[str, tuple[int, int]] = {}
    for rel, meta in listing.items():
        head, sep, _ = rel.partition("/")
        if sep:
            dirs.setdefault(head, {})[rel] = meta
        else:
            root_files[rel] = meta
    return dirs, root_files


def fingerprint(listing: dict[str, tuple[int, int]]) -> str:
    """Order-independent sha1 over (path, size, mtime_ns). Empty listing has a stable fingerprint."""
    h = hashlib.sha1()
    for rel in sorted(listing):
        size, mtime_ns = listing[rel]
        h.update(f"{rel}\0{size}\0{mtime_ns}\n".encode())
    return h.hexdigest()


def diff_uploaded(current: dict[str, tuple[int, int]], uploaded: dict[str, tuple[int, int]]) -> tuple[list[str], list[str]]:
    """
    Compare the current files of a directory with the files already uploaded from it.
    Returns (modified, deleted). New files are not reported — they can still be sent.
    """
    modified = sorted(rel for rel, meta in uploaded.items() if rel in current and current[rel] != meta)
    deleted  = sorted(rel for rel in uploaded if rel not in current)
    return modified, deleted


def conflict_detail(directory: str, modified: list[str], deleted: list[str]) -> str:
    lines = [f"Directory '{directory}' changed after it was sent to the TRE."]
    if modified:
        lines.append(f"Modified ({len(modified)}): " + ", ".join(modified[:_MAX_FILES_IN_DETAIL])
                     + (" …" if len(modified) > _MAX_FILES_IN_DETAIL else ""))
    if deleted:
        lines.append(f"Deleted ({len(deleted)}): " + ", ".join(deleted[:_MAX_FILES_IN_DETAIL])
                     + (" …" if len(deleted) > _MAX_FILES_IN_DETAIL else ""))
    lines.append("Uploaded objects cannot be overwritten. Check the instrument output and contact the TRE administrator.")
    return "\n".join(lines)


def list_top_level_dirs(run_folder: str, exclusions: list[str]) -> list[str]:
    """Top-level directory names of a run (includes empty ones), minus hidden/excluded names."""
    all_exclusions = BUILTIN_EXCLUSIONS + (exclusions or [])
    names = []
    for entry in os.scandir(run_folder):
        if entry.is_dir() and not _is_excluded(entry.name, all_exclusions):
            names.append(entry.name)
    return sorted(names)


def uploaded_files(run_uuid, db, directory: str | None = None) -> dict[str, tuple[int, int]]:
    """{rel_path: (size, mtime_ns)} of uploaded files for a run, optionally limited to one top-level directory."""
    from db.models.run_files import RunFiles
    q = db.query(RunFiles).filter(RunFiles.run_uuid == run_uuid, RunFiles.uploaded == True)
    if directory is not None:
        q = q.filter(RunFiles.rel_path.startswith(f"{directory}/", autoescape=True))
    return {f.rel_path: (f.size, f.mtime_ns) for f in q.all()}


def known_digests(run_uuid, db) -> dict[str, tuple[int, int, str]]:
    """{rel_path: (size, mtime_ns, sha256)} of every hashed file of a run — used to skip re-hashing."""
    from db.models.run_files import RunFiles
    rows = db.query(RunFiles).filter(RunFiles.run_uuid == run_uuid).all()
    return {f.rel_path: (f.size, f.mtime_ns, f.sha256) for f in rows}


def mark_run_conflict(run, db, detail: str):
    """Move a run to transfer_conflict and record why in its status history."""
    from db.repositories.runs_status_history import add_run_status_history
    run.status = RUN_CONFLICT_STATUS
    db.commit()
    add_run_status_history(run_uuid=run.uuid, status=RUN_CONFLICT_STATUS, db=db, detail=detail)
    logger.warning(f"run '{run.name}' → {RUN_CONFLICT_STATUS}: {detail}")


def process_run(run, sequencer, db, publish, now: datetime | None = None) -> None:
    """
    One watcher pass over a single 'running' run of a directory_stability instrument.
    Updates run_directories and the run's activity fields, then publishes
    run_directory_upload_requested / run_completed as needed.
    """
    from db.models.run_directories import RunDirectories

    now          = now or datetime.now()
    st           = sequencer.type
    dir_minutes  = st.dir_stability_minutes or 10
    run_minutes  = st.run_stability_minutes or 60
    send_early   = sequencer.sent_to_tre == "auto"
    exclusions   = sequencer.exclusions or []
    run_folder   = os.path.join(sequencer.location, run.name)

    if not os.path.isdir(run_folder):
        logger.warning(f"directory stability: run folder not accessible: {run_folder}")
        return

    listing          = scan_tree(run_folder, exclusions)
    dir_listings, _  = split_top_level(listing)
    top_dirs         = list_top_level_dirs(run_folder, exclusions)
    rows             = {d.name: d for d in db.query(RunDirectories).filter(RunDirectories.run_uuid == run.uuid).all()}

    to_publish: list[str] = []
    conflicts:  list[str] = []

    for name in top_dirs:
        sub = dir_listings.get(name, {})
        fp  = fingerprint(sub)
        row = rows.get(name)

        if row is None:
            db.add(RunDirectories(run_uuid=run.uuid, name=name, state=WAITING, fingerprint=fp, stable_since=now,
                                  file_count=len(sub), total_bytes=sum(s for s, _ in sub.values())))
            logger.info(f"directory stability: tracking {run.name}/{name}")
            continue

        if row.state == CONFLICT:
            continue

        if fp != row.fingerprint:
            row.fingerprint  = fp
            row.stable_since = now
            row.file_count   = len(sub)
            row.total_bytes  = sum(s for s, _ in sub.values())
            if row.state in (SENT, FAILED):
                modified, deleted = diff_uploaded(sub, uploaded_files(run.uuid, db, name))
                if modified or deleted:
                    row.state  = CONFLICT
                    row.detail = conflict_detail(name, modified, deleted)
                    conflicts.append(row.detail)
                elif row.state == SENT:
                    # only new files — send them once the directory is quiet again
                    row.state = WAITING
                    logger.info(f"directory stability: new files in sent directory {run.name}/{name} — waiting again")
            continue

        quiet_for = now - (row.stable_since or now)
        if row.state == WAITING and send_early and quiet_for >= timedelta(minutes=dir_minutes):
            row.state = QUEUED
            to_publish.append(name)

    # a directory that was (partly) sent and then removed is a conflict too
    for name, row in rows.items():
        if name in top_dirs or row.state == CONFLICT:
            continue
        if uploaded_files(run.uuid, db, name):
            row.state  = CONFLICT
            row.detail = f"Directory '{name}' was removed after it was sent to the TRE."
            conflicts.append(row.detail)
        elif row.state in (WAITING, FAILED):
            db.delete(row)

    run_fp = fingerprint(listing)
    if run.activity_fingerprint != run_fp or run.last_change_at is None:
        run.activity_fingerprint = run_fp
        run.last_change_at       = now
    db.commit()

    if conflicts:
        mark_run_conflict(run, db, "\n\n".join(conflicts))
        return

    for name in to_publish:
        logger.info(f"directory stability: {run.name}/{name} quiet for {dir_minutes} min — queuing upload")
        publish("run_directory_upload_requested", run.name, sequencer.uuid, directory=name)

    busy = db.query(RunDirectories).filter(
        RunDirectories.run_uuid == run.uuid,
        RunDirectories.state.in_([QUEUED, UPLOADING]),
    ).count()
    if busy:
        return

    if now - run.last_change_at >= timedelta(minutes=run_minutes):
        logger.info(f"run completed (directory_stability): {run.name} quiet for {run_minutes} min")
        publish("run_completed", run.name, sequencer.uuid)
