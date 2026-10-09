import os
import sys
import json
import time
import threading
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pika

import db.base  # registers all models so SQLAlchemy can resolve all relationships
from db.session import SESSION_LOCAL
from db.models.runs import Runs
from db.models.sequencers import Sequencers
from db.repositories.runs import create_run, update_run_status
from db.repositories.runs_status_history import add_run_status_history
import glob

from services.checksum import create_checksum_file, find_file_by_hash, _fmt_bytes, _sha256
from services.tre import send_to_tre, check_verify_status, find_checksum_filename_in_s3, upload_file_list
from db.models.runs_status_history import RunsStatusHistory
from sqlalchemy import func
from services import dir_stability
from db.models.run_directories import RunDirectories
from db.models.run_files import RunFiles
from datetime import datetime
from db.repositories.settings import get_setting_int
from core.logger import get_logger

logger = get_logger("worker")

RABBITMQ_URL   = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_EVENTS   = "runs_events"    # run_created, run_completed  — fast, always processed immediately
QUEUE_PIPELINE = "runs_pipeline"  # checksum, upload, verify    — slow, one at a time


def resolve_verify_detail(tre_error: str | None, run_folder: str, retries: int) -> str:
    """
    If tre_error looks like a SHA256 hash, find the matching filename in the run folder.
    Logs the result and returns a human-readable detail string.
    """
    if not tre_error:
        detail = f"checksum not found on S3 after {retries} retries"
        logger.warning(f"[verify] {detail}")
        return detail

    if len(tre_error.strip()) == 64 and all(c in "0123456789abcdefABCDEF" for c in tre_error.strip()):
        hash_value = tre_error.strip()
        logger.warning(f"[verify] TRE reported failed file — hash: {hash_value} — scanning run folder to resolve filename")
        filename = find_file_by_hash(run_folder, hash_value)
        if filename:
            detail = f"File failed verification: {filename} (sha256: {hash_value})"
            logger.warning(f"[verify] resolved: {detail}")
        else:
            detail = f"File failed verification — sha256: {hash_value} (file not found in run folder)"
            logger.warning(f"[verify] {detail}")
        return detail

    logger.warning(f"[verify] TRE error: {tre_error}")
    return tre_error


PROGRESS_MIN_INTERVAL = 2.0  # seconds between progress writes to the DB


def _throttled(write, min_interval: float = PROGRESS_MIN_INTERVAL):
    """
    Wrap a progress writer so it hits the DB at most once per min_interval.
    boto3 reports upload progress about 4× per MB (~4 million times per TB); writing
    each one to the DB under the upload lock slowed large transfers. The first and
    the final update (done == total) are always written.
    """
    last = [0.0]

    def callback(done: int, total: int, bytes_done: int, total_bytes: int):
        now = time.monotonic()
        final = total_bytes and bytes_done >= total_bytes or (total and done >= total)
        if not final and last[0] and now - last[0] < min_interval:
            return
        last[0] = now
        write(done, total, bytes_done, total_bytes)
    return callback


def _make_progress_callback(run_uuid):
    """Returns a (throttled) callback that writes checksum / upload progress to the run's progress column."""
    @_throttled
    def callback(done: int, total: int, bytes_done: int, total_bytes: int):
        text = f"{_fmt_bytes(bytes_done)} / {_fmt_bytes(total_bytes)}"
        db = SESSION_LOCAL()
        try:
            run = db.query(Runs).filter(Runs.uuid == run_uuid).first()
            if run:
                run.progress = text
                db.commit()
        except Exception as e:
            logger.warning(f"failed to update progress for run {run_uuid}: {e}")
        finally:
            db.close()
    return callback


def resolve_checksum_filename(run_name: str, sequencer_uuid, db) -> str | None:
    """
    Read the checksum filename stored in DB after checksumming completed.
    Returns the filename (e.g. "abc123.CHECKSUM") or None.
    """
    from db.models.runs import Runs
    run = db.query(Runs).filter(Runs.name == run_name, Runs.sequencer_uuid == sequencer_uuid).first()
    if run and run.checksum_file:
        logger.info(f"[verify] checksum filename from DB: {run.checksum_file}")
        return run.checksum_file
    logger.warning(f"[verify] no checksum_file stored in DB for run '{run_name}'")
    return None


def get_sequencer(sequencer_uuid) -> Sequencers | None:
    """
    Fetches the full sequencer row from the DB.
    Used to read location, sent_to_tre, and delete_after_confirmation.
    """
    db = SESSION_LOCAL()
    try:
        sequencer = db.query(Sequencers).filter(Sequencers.uuid == sequencer_uuid).first()
        if sequencer:
            _ = sequencer.type  # load relationship while session is open
        return sequencer
    finally:
        db.close()


def _uses_directory_stability(sequencer) -> bool:
    return bool(sequencer.type and sequencer.type.completion_method == "directory_stability")


def record_digests(run_uuid, digests: dict[str, tuple[int, int, str]], db):
    """
    Store {rel_path: (size, mtime_ns, sha256)} from the checksum step in run_files.
    A file that is unchanged (same size, mtime and digest) keeps its 'uploaded' flag, so a
    retry does not send it again; anything else is recorded as not uploaded.
    """
    existing = {f.rel_path: f for f in db.query(RunFiles).filter(RunFiles.run_uuid == run_uuid).all()}
    for rel, (size, mtime_ns, sha) in digests.items():
        f = existing.get(rel)
        if f is None:
            db.add(RunFiles(run_uuid=run_uuid, rel_path=rel, size=size, mtime_ns=mtime_ns, sha256=sha, uploaded=False))
        elif (f.size, f.mtime_ns, f.sha256) != (size, mtime_ns, sha):
            f.size, f.mtime_ns, f.sha256, f.uploaded = size, mtime_ns, sha, False
    db.commit()


def mark_uploaded(run_uuid, rel_path: str, db):
    """Flag one file as uploaded (it was hashed in the checksum step). Unknown paths (the .CHECKSUM) are ignored."""
    f = db.query(RunFiles).filter(RunFiles.run_uuid == run_uuid, RunFiles.rel_path == rel_path).first()
    if f is not None and not f.uploaded:
        f.uploaded = True
        db.commit()


class DirectoryConflict(Exception):
    pass


def _dir_progress_callback(dir_uuid):
    """Returns a (throttled) callback that writes upload progress to the directory's progress column."""
    @_throttled
    def callback(done: int, total: int, bytes_done: int, total_bytes: int):
        db = SESSION_LOCAL()
        try:
            row = db.query(RunDirectories).filter(RunDirectories.uuid == dir_uuid).first()
            if row:
                row.progress = f"{done} / {total} files · {_fmt_bytes(bytes_done)} / {_fmt_bytes(total_bytes)}"
                db.commit()
        except Exception as e:
            logger.warning(f"failed to update progress for directory {dir_uuid}: {e}")
        finally:
            db.close()
    return callback


def handle_run_directory_upload_requested(name: str, sequencer_uuid, directory: str):
    """
    Directory stability: one top-level directory of a still-running run has been quiet
    for dir_stability_minutes. Hash and upload the files in it that were not sent yet.
    No .CHECKSUM is uploaded here — the TRE trigger is only sent at finalization.
      queued → uploading → sent
                         → failed    (upload error — Retry, or finalization picks the files up)
                         → conflict  (an already-sent file changed — run goes to transfer_conflict)
    """
    logger.info(f"run_directory_upload_requested → name={name} directory={directory} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        sequencer = get_sequencer(sequencer_uuid)
        run = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
        row = run and db.query(RunDirectories).filter(RunDirectories.run_uuid == run.uuid, RunDirectories.name == directory).first()
        if not sequencer or not run or not row or run.is_deleted or run.status != "running" or row.state != dir_stability.QUEUED:
            logger.warning(f"run_directory_upload_requested ignored for '{name}/{directory}' — "
                           f"run_status={run.status if run else None} dir_state={row.state if row else None}")
            return

        row.state    = dir_stability.UPLOADING
        row.detail   = None
        row.progress = "scanning files…"
        db.commit()

        run_folder = os.path.join(sequencer.location, name)
        dir_path   = os.path.join(run_folder, directory)
        current    = dir_stability.scan_tree(dir_path, sequencer.exclusions or [], prefix=directory)
        uploaded   = dir_stability.uploaded_files(run.uuid, db, directory)

        modified, deleted = dir_stability.diff_uploaded(current, uploaded)
        if modified or deleted:
            raise DirectoryConflict(dir_stability.conflict_detail(directory, modified, deleted))

        pending = sorted(rel for rel in current if rel not in uploaded)
        logger.info(f"[dir upload] {name}/{directory}: {len(pending)} file(s) to send, {len(uploaded)} already sent")

        # hash first; the digest is only trusted if the file is unchanged after the upload
        hashed: dict[str, tuple[int, int, str]] = {}
        for i, rel in enumerate(pending, 1):
            size, mtime_ns = current[rel]
            hashed[rel] = (size, mtime_ns, _sha256(os.path.join(run_folder, rel)))
            if i % 100 == 0 or i == len(pending):
                row.progress = f"hashing {i} / {len(pending)} files"
                db.commit()

        def _record(local_path, relative_path):
            rel = os.path.relpath(local_path, run_folder).replace(os.sep, "/")
            size, mtime_ns, digest = hashed[rel]
            st = os.stat(local_path)
            if (st.st_size, st.st_mtime_ns) != (size, mtime_ns):
                raise DirectoryConflict(dir_stability.conflict_detail(directory, [rel], []))
            f = db.query(RunFiles).filter(RunFiles.run_uuid == run.uuid, RunFiles.rel_path == rel).first()
            if f is None:
                f = RunFiles(run_uuid=run.uuid, rel_path=rel)
                db.add(f)
            f.size, f.mtime_ns, f.sha256, f.uploaded = size, mtime_ns, digest, True
            db.commit()

        if pending:
            upload_file_list(
                [(os.path.join(run_folder, rel), os.path.join(name, rel)) for rel in pending],
                sequencer.slug,
                on_progress=_dir_progress_callback(row.uuid),
                on_file_done=_record,
            )

        db.refresh(row)
        row.state    = dir_stability.SENT
        row.sent_at  = datetime.now()
        row.progress = None
        db.commit()
        logger.info(f"[dir upload] {name}/{directory} sent")

    except DirectoryConflict as e:
        logger.warning(f"[dir upload] conflict in '{name}/{directory}': {e}")
        db.rollback()
        row.state, row.detail, row.progress = dir_stability.CONFLICT, str(e), None
        db.commit()
        if run.status == "running":
            dir_stability.mark_run_conflict(run, db, str(e))
    except Exception as e:
        logger.error(f"[dir upload] FAILED for '{name}/{directory}': {e}", exc_info=True)
        try:
            db.rollback()
            row.state, row.detail, row.progress = dir_stability.FAILED, str(e), None
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def handle_run_created(name: str, sequencer_uuid: str):
    """
    A new run folder was detected by the watcher.
    Insert it into the DB with status = "running".
    """
    logger.info(f"run_created → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        # Guard: PollingObserver fires on_created for ALL existing folders on startup,
        # so this event can arrive for a run that is already in the DB (e.g. after
        # watcher restart). Skip silently to avoid duplicate rows.
        existing = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
        if existing:
            logger.warning(f"run_created ignored for '{name}' — already in DB (status={existing.status})")
            return

        run = create_run(name=name, sequencer_uuid=sequencer_uuid, db=db)
        add_run_status_history(run_uuid=run.uuid, status="running", db=db)
        logger.info(f"saved run '{name}' to DB")
    except Exception as e:
        logger.error(f"failed to save run '{name}': {e}", exc_info=True)
    finally:
        db.close()


def handle_run_completed(name: str, sequencer_uuid):
    """
    Completion signal detected by the watcher.
    Sets status to running_finished, then checks the sequencer's
    sent_to_tre setting:
      - auto   → immediately publish run_upload_requested so the worker
                 continues the pipeline without waiting
      - manual → stop here; a button in the UI will trigger the next step
    """
    logger.info(f"run_completed → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        # guard: skip if the run has already moved past running_finished
        existing = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
        if existing and (existing.is_deleted or existing.status != "running"):
            logger.warning(f"run_completed ignored for '{name}' — is_deleted={existing.is_deleted} status='{existing.status}'")
            return

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="running_finished", db=db)
        add_run_status_history(run_uuid=run.uuid, status="running_finished", db=db)
        logger.info(f"status updated to 'running_finished' for run '{name}'")

        sequencer = get_sequencer(sequencer_uuid)
        if not sequencer:
            logger.error(f"sequencer {sequencer_uuid} not found — cannot determine sent_to_tre setting")
            return

        if sequencer.sent_to_tre == "auto":
            logger.info(f"sent_to_tre=auto — publishing run_checksum_requested for '{name}'")
            from services.publisher import publish
            publish("run_checksum_requested", name, sequencer_uuid)
        else:
            logger.info(f"sent_to_tre=manual — waiting for user to trigger upload for '{name}'")

    except Exception as e:
        logger.error(f"failed to handle run_completed for '{name}': {e}", exc_info=True)
    finally:
        db.close()


def handle_run_checksum_requested(name: str, sequencer_uuid):
    """
    Triggered after running_finished (auto) or by the "Send to TRE" button (manual).
    1. Set status to checksumming
    2. Generate checksum.txt inside the run folder (SHA256 per file)
    3. Publish run_upload_requested so the worker continues to S3 upload
    """
    logger.info(f"run_checksum_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        sequencer = get_sequencer(sequencer_uuid)
        if not sequencer:
            logger.error(f"sequencer {sequencer_uuid} not found — cannot checksum run '{name}'")
            return

        # Guard: skip if run is already actively processing or done.
        # NOTE: do NOT include "queued" here — the start-upload API sets status=queued
        # BEFORE publishing run_checksum_requested, so the worker would discard the
        # legitimate first event if queued were in this list.
        # - move_failed: cancelled by user
        # - checksumming / moving / verifying: already in flight (stale duplicate event)
        # - completed: already done
        existing = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
        stale_queued = existing and existing.status == "queued" and bool(existing.checksum_file)
        if existing and (existing.is_deleted or stale_queued or existing.status in ("move_failed", "verify_failed", "checksumming", "moving", "verifying", "completed")):
            logger.warning(f"run_checksum_requested ignored for '{name}' — is_deleted={existing.is_deleted} status='{existing.status}' stale_queued={stale_queued}")
            return

        # If checksum_file was cleared in DB (user triggered a fresh retry via the API),
        # delete any stale .CHECKSUM file on disk so create_checksum_file re-generates it.
        # This prevents reusing an old checksum after the run folder contents have changed.
        if existing and not existing.checksum_file:
            run_folder = os.path.join(sequencer.location, name)
            stale_checksums = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
            for f in stale_checksums:
                os.remove(f)
                logger.info(f"deleted stale checksum file before re-checksumming: {os.path.basename(f)}")

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="checksumming", db=db)
        add_run_status_history(run_uuid=run.uuid, status="checksumming", db=db)
        logger.info(f"status updated to 'checksumming' for run '{name}'")

        # reuse digests of files hashed before (sent early by directory stability, or an earlier
        # attempt of this run) when size and mtime are unchanged — no re-hashing of terabytes on retry
        known   = dir_stability.known_digests(run.uuid, db)
        digests = {}
        checksum_path = create_checksum_file(run_name=name, sequencer_location=sequencer.location, exclusions=sequencer.exclusions or [], on_progress=_make_progress_callback(run.uuid), known_digests=known,
                                             on_digest=lambda rel, size, mtime_ns, sha: digests.__setitem__(rel, (size, mtime_ns, sha)))
        record_digests(run.uuid, digests, db)

        # checksumming done — store filename in DB, set queued, clear progress
        run_obj = db.query(Runs).filter(Runs.uuid == run.uuid).first()
        if run_obj:
            run_obj.status        = "queued"
            run_obj.progress      = None
            run_obj.checksum_file = os.path.basename(checksum_path)
            db.commit()
            logger.info(f"stored checksum_file='{run_obj.checksum_file}' for run '{name}'")
        add_run_status_history(run_uuid=run.uuid, status="queued", db=db)

        from services.publisher import publish
        publish("run_upload_requested", name, sequencer_uuid)
        logger.info(f"checksum done — published run_upload_requested for '{name}'")

    except Exception as e:
        logger.error(f"failed during checksum for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="move_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="move_failed", db=db, detail=str(e))
        except Exception:
            pass
    finally:
        db.close()


def handle_run_upload_requested(name: str, sequencer_uuid):
    """
    Triggered either automatically (sent_to_tre=auto) or by a manual button click.
    Uploads the run folder directly to S3 — no zipping.
    1. Set status to moving  → upload → on error: move_failed
    2. Set status to verifying → poll S3 for TRE confirmation → on error: verify_failed
    3. Set status to completed
    """
    logger.info(f"run_upload_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()

    sequencer = get_sequencer(sequencer_uuid)
    if not sequencer:
        logger.error(f"sequencer {sequencer_uuid} not found — cannot upload run '{name}'")
        db.close()
        return

    # Guard: skip if run was cancelled, deleted, or a verify-only retry is already in progress
    existing = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
    if existing and (existing.is_deleted or existing.status in ("move_failed", "verify_failed", "verifying", "completed")):
        logger.warning(f"run_upload_requested ignored for '{name}' — is_deleted={existing.is_deleted} status='{existing.status}'")
        db.close()
        return

    # ── step 1: upload ────────────────────────────────────────────────────────
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="moving", db=db)
        run.progress = "scanning files…"
        db.commit()
        add_run_status_history(run_uuid=run.uuid, status="moving", db=db)
        logger.info(f"status updated to 'moving' for run '{name}'")

        # resume: files already sent (earlier attempt, or directory stability) are skipped when unchanged
        already    = dir_stability.uploaded_files(run.uuid, db)
        run_folder = os.path.join(sequencer.location, name)
        if already:
            logger.info(f"[upload] '{name}': {len(already)} file(s) already sent — skipped if unchanged")
        send_to_tre(run_name=name, sequencer_location=sequencer.location, sequencer_slug=sequencer.slug, exclusions=sequencer.exclusions or [], on_progress=_make_progress_callback(run.uuid), already_uploaded=already,
                    on_file_done=lambda local_path, _rel: mark_uploaded(run.uuid, os.path.relpath(local_path, run_folder).replace(os.sep, "/"), db))
        logger.info(f"run folder uploaded to S3 for run '{name}'")

    except Exception as e:
        logger.error(f"[upload] FAILED for run '{name}': {e}", exc_info=True)
        try:
            # Only set move_failed if still in 'moving' — a retry click may have already
            # changed the status to 'queued', in which case we must not overwrite it.
            current = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
            if current and current.status == "moving":
                run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="move_failed", db=db)
                add_run_status_history(run_uuid=run.uuid, status="move_failed", db=db, detail=str(e))
            else:
                logger.info(f"[upload] not setting move_failed — status is already '{current.status if current else 'unknown'}' (retry in progress?)")
        except Exception:
            pass
        db.close()
        return

    # ── step 2: hand over to the verifier ─────────────────────────────────────
    # The TRE takes minutes to confirm. Waiting here would hold the single pipeline
    # slot, so the next run could not upload. The verifier thread picks the run up.
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="verifying", db=db)
        run.progress = None
        db.commit()
        add_run_status_history(run_uuid=run.uuid, status="verifying", db=db)
        logger.info(f"status updated to 'verifying' for run '{name}' — verifier will poll the TRE")
    except Exception as e:
        logger.error(f"failed to set '{name}' to verifying: {e}", exc_info=True)
    finally:
        db.close()


def handle_run_rechecksum_requested(name: str, sequencer_uuid):
    """
    Triggered when the user wants to force a fresh checksum after verify_failed.
    Deletes the existing .CHECKSUM file(s) first, then runs the full
    checksum → upload → verify pipeline from scratch.
    """
    logger.info(f"run_rechecksum_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        sequencer = get_sequencer(sequencer_uuid)
        if not sequencer:
            logger.error(f"sequencer {sequencer_uuid} not found — cannot rechecksum run '{name}'")
            return

        existing = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
        if existing and existing.is_deleted:
            logger.warning(f"run_rechecksum_requested ignored for '{name}' — run is deleted")
            return

        run_folder = os.path.join(sequencer.location, name)
        existing = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
        for f in existing:
            os.remove(f)
            logger.info(f"deleted old checksum file: {os.path.basename(f)}")

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="checksumming", db=db)
        add_run_status_history(run_uuid=run.uuid, status="checksumming", db=db)
        logger.info(f"status updated to 'checksumming' for run '{name}'")

        # forced fresh checksum: hash everything again, but record the result so the upload can resume
        digests = {}
        checksum_path = create_checksum_file(run_name=name, sequencer_location=sequencer.location, exclusions=sequencer.exclusions or [], on_progress=_make_progress_callback(run.uuid),
                                             on_digest=lambda rel, size, mtime_ns, sha: digests.__setitem__(rel, (size, mtime_ns, sha)))
        record_digests(run.uuid, digests, db)

        # checksumming done — store filename in DB, set queued, clear progress
        run_obj = db.query(Runs).filter(Runs.uuid == run.uuid).first()
        if run_obj:
            run_obj.status        = "queued"
            run_obj.progress      = None
            run_obj.checksum_file = os.path.basename(checksum_path)
            db.commit()
            logger.info(f"stored checksum_file='{run_obj.checksum_file}' for run '{name}'")
        add_run_status_history(run_uuid=run.uuid, status="queued", db=db)

        from services.publisher import publish
        publish("run_upload_requested", name, sequencer_uuid)
        logger.info(f"rechecksum done — published run_upload_requested for '{name}'")

    except Exception as e:
        logger.error(f"failed during rechecksum for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="move_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="move_failed", db=db, detail=str(e))
        except Exception:
            pass
    finally:
        db.close()


def handle_run_verify_requested(name: str, sequencer_uuid):
    """
    Retry verification only. Verification itself runs in the verifier thread,
    so this just (re)starts the wait by setting the run to 'verifying'.
    Kept for messages published before the verifier existed.
    """
    logger.info(f"run_verify_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        run = db.query(Runs).filter(Runs.name == name, Runs.sequencer_uuid == sequencer_uuid).first()
        if not run or run.is_deleted or run.status in ("verifying", "completed"):
            logger.info(f"run_verify_requested: nothing to do for '{name}' (status={run.status if run else None})")
            return
        run.status   = "verifying"
        run.progress = None
        db.commit()
        add_run_status_history(run_uuid=run.uuid, status="verifying", db=db)
    finally:
        db.close()


# ── TRE verifier ──────────────────────────────────────────────────────────────

def _verifying_since(run, db) -> datetime:
    """When the current verification wait started (latest 'verifying' history entry)."""
    since = (
        db.query(func.max(RunsStatusHistory.created_at))
        .filter(RunsStatusHistory.run_uuid == run.uuid, RunsStatusHistory.status == "verifying")
        .scalar()
    )
    return since or run.updated_at or datetime.now()


def _finish_verification(run, db, new_status: str, detail: str | None = None):
    """Set completed / verify_failed — only if the run is still verifying (a retry or cancel may have changed it)."""
    db.refresh(run)
    if run.status != "verifying":
        return
    run.status = new_status
    db.commit()
    add_run_status_history(run_uuid=run.uuid, status=new_status, db=db, detail=detail)
    log = logger.info if new_status == "completed" else logger.warning
    log(f"[verifier] '{run.name}' → {new_status}" + (f": {detail}" if detail else ""))


def check_verifying_run(run, db, now: datetime | None = None):
    """
    One single-shot TRE check for one run in 'verifying':
      empty confirmation file   → completed
      file with content         → verify_failed (TRE reported a problem)
      not there yet / S3 error  → keep waiting until the deadline:
                                  verify_retries × verify_interval, plus verify_minutes_per_100gb
                                  per 100 GB of run data (1 h + 24 min/100 GB by default: 1 TB → 5 h)
    """
    now      = now or datetime.now()
    retries  = get_setting_int("verify_retries", 60)
    interval = get_setting_int("verify_interval", 60)
    # the TRE re-hashes every byte before it confirms — large runs get extra time
    per_100gb = get_setting_int("verify_minutes_per_100gb", 24)
    # SUM(bigint) comes back from Postgres as Decimal
    run_bytes = int(db.query(func.coalesce(func.sum(RunFiles.size), 0)).filter(RunFiles.run_uuid == run.uuid).scalar() or 0)
    deadline  = retries * interval + int(run_bytes / 100e9 * per_100gb * 60)   # proportional to size

    if not run.checksum_file:
        _finish_verification(run, db, "verify_failed", "checksum filename not found in DB — re-upload required")
        return

    result = check_verify_status(run.checksum_file)
    status = result.get("status")

    if status == "success":
        _finish_verification(run, db, "completed")
    elif status == "failed":
        sequencer  = get_sequencer(run.sequencer_uuid)
        run_folder = os.path.join(sequencer.location, run.name) if sequencer else ""
        _finish_verification(run, db, "verify_failed", resolve_verify_detail(result.get("detail"), run_folder, retries))
    else:
        waited = (now - _verifying_since(run, db)).total_seconds()
        if status == "error":
            logger.warning(f"[verifier] S3 error for '{run.name}': {result.get('detail')}")
        if waited >= deadline:
            minutes = round(deadline / 60)
            _finish_verification(run, db, "verify_failed",
                                 f"TRE confirmation not received within {minutes} min ({retries} checks). "
                                 f"The TRE may still be processing — use Retry Verification later.")
        else:
            logger.debug(f"[verifier] '{run.name}' pending ({waited:.0f}s / {deadline}s)")


def check_verifying_runs():
    """One pass over every run waiting for TRE confirmation."""
    db = SESSION_LOCAL()
    try:
        runs = db.query(Runs).filter(Runs.status == "verifying", Runs.is_deleted == False).all()
        for run in runs:
            try:
                check_verifying_run(run, db)
            except Exception as e:
                db.rollback()
                logger.error(f"[verifier] error checking '{run.name}': {e}", exc_info=True)
    finally:
        db.close()


def _verifier_loop():
    logger.info("verifier started — polling TRE confirmations for runs in 'verifying'")
    while True:
        try:
            check_verifying_runs()
        except Exception as e:
            logger.error(f"[verifier] pass failed: {e}", exc_info=True)
        time.sleep(get_setting_int("verify_interval", 60))


def dispatch(body: bytes):
    """Parse one message and run its handler. Errors are logged, never raised."""
    try:
        message = json.loads(body)
        event          = message.get("event")
        name           = message.get("name")
        sequencer_uuid = UUID(message.get("sequencer_uuid"))

        if event == "run_created":
            handle_run_created(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_completed":
            handle_run_completed(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_checksum_requested":
            handle_run_checksum_requested(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_upload_requested":
            handle_run_upload_requested(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_verify_requested":
            handle_run_verify_requested(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_rechecksum_requested":
            handle_run_rechecksum_requested(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_directory_upload_requested":
            handle_run_directory_upload_requested(name=name, sequencer_uuid=sequencer_uuid, directory=message.get("directory"))

        else:
            logger.warning(f"unknown event: {event}")

    except Exception as e:
        logger.error(f"failed to process message: {e}", exc_info=True)


def on_message(channel, method, properties, body):
    """
    Events queue: handlers are fast DB operations, so run them inline and ack.
    ack tells RabbitMQ "I processed this message, remove it from the queue";
    without ack, RabbitMQ keeps the message and re-delivers it if the worker restarts.
    """
    try:
        dispatch(body)
    finally:
        channel.basic_ack(delivery_tag=method.delivery_tag)


def on_pipeline_message(channel, method, properties, body):
    """
    Pipeline queue: checksum / upload / verify can take hours. Running them inside
    this callback would block pika's I/O loop, so no heartbeats are sent, RabbitMQ
    closes the connection after ~3 min ("missed heartbeats from client"), the ack
    fails, the worker crashes and the message is redelivered.

    Instead the task runs in its own thread while start_consuming() keeps the
    connection alive. The ack is handed back to the connection thread with
    add_callback_threadsafe (pika channels are not thread-safe). prefetch_count=1
    means no new pipeline message is delivered until this ack, so tasks still run
    one at a time.
    """
    connection = channel.connection
    delivery_tag = method.delivery_tag

    def _ack():
        if channel.is_open:
            channel.basic_ack(delivery_tag=delivery_tag)
        else:
            logger.warning(f"channel closed before ack (delivery_tag={delivery_tag}) — message will be redelivered")

    def _run():
        try:
            dispatch(body)
        except Exception as e:
            logger.error(f"pipeline task crashed: {e}", exc_info=True)
        finally:
            try:
                connection.add_callback_threadsafe(_ack)
            except Exception as e:
                logger.error(f"could not schedule ack (delivery_tag={delivery_tag}): {e}")

    threading.Thread(target=_run, daemon=True, name="pipeline-task").start()


def recover_stuck_runs():
    """
    On worker startup, find any runs stuck in intermediate states
    (checksumming / moving) and move them to the appropriate
    failed status so the retry button picks up from the right stage:
      checksumming → failed       (retry re-checksums and re-uploads)
      moving       → move_failed  (retry re-uploads only)
    Runs in 'verifying' are left alone — the verifier thread resumes them.
    """
    RECOVERY_MAP = {
        "checksumming": ("failed",       "Worker restarted during checksumming — use Retry to resume"),
        "moving":       ("move_failed",  "Worker restarted during upload — use Retry Upload to resume"),
    }
    db = SESSION_LOCAL()
    try:
        stuck = db.query(Runs).filter(Runs.status.in_(list(RECOVERY_MAP))).all()
        for run in stuck:
            new_status, detail = RECOVERY_MAP[run.status]
            logger.warning(f"recovering stuck run '{run.name}' (status={run.status}) → {new_status}")
            run.status   = new_status
            run.progress = None
            db.flush()
            add_run_status_history(run_uuid=run.uuid, status=new_status, db=db, detail=detail)
        db.commit()
        if stuck:
            logger.info(f"recovered {len(stuck)} stuck run(s)")

        # directory stability: a directory upload interrupted by the restart
        stuck_dirs = db.query(RunDirectories).filter(RunDirectories.state == dir_stability.UPLOADING).all()
        for row in stuck_dirs:
            logger.warning(f"recovering stuck directory upload '{row.name}' (run {row.run_uuid}) → failed")
            row.state    = dir_stability.FAILED
            row.progress = None
            row.detail   = "Worker restarted during upload — use Retry to resume"
        db.commit()
    except Exception as e:
        logger.error(f"failed to recover stuck runs: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def recover_auto_runs():
    """
    On worker startup, find any runs stuck in 'running_finished' with
    sent_to_tre=auto that have no pending RabbitMQ event (e.g. after a
    restart). Re-publishes run_checksum_requested for each so they
    resume the pipeline automatically without manual intervention.
    """
    db = SESSION_LOCAL()
    try:
        stranded = (
            db.query(Runs)
            .join(Sequencers, Runs.sequencer_uuid == Sequencers.uuid)
            .filter(
                Runs.status == "running_finished",
                Runs.is_deleted == False,
                Sequencers.sent_to_tre == "auto",
            )
            .all()
        )
        if not stranded:
            return

        from services.publisher import publish
        logger.info(f"found {len(stranded)} stranded auto run(s) in 'running_finished' — re-queuing")
        for run in stranded:
            logger.info(f"re-queuing run_checksum_requested for '{run.name}' (sequencer_uuid={run.sequencer_uuid})")
            publish("run_checksum_requested", run.name, run.sequencer_uuid)
    except Exception as e:
        logger.error(f"failed to recover auto runs: {e}", exc_info=True)
    finally:
        db.close()


def _connect_rabbitmq(label: str):
    """Connect to RabbitMQ with retries. Returns a pika BlockingConnection."""
    for attempt in range(1, 11):
        try:
            return pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        except Exception as e:
            logger.warning(f"[{label}] attempt {attempt}/10 failed to connect to RabbitMQ: {e} — retrying in 5s...")
            time.sleep(5)
    logger.error(f"[{label}] could not connect to RabbitMQ after 10 attempts, exiting.")
    sys.exit(1)


def _start_events_consumer():
    """
    Consumes from runs_events in a daemon thread.
    Handles run_created and run_completed — fast DB operations that must
    never be blocked by a long upload on the pipeline queue.
    """
    connection = _connect_rabbitmq("events")
    channel    = connection.channel()
    channel.queue_declare(queue=QUEUE_EVENTS, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_EVENTS, on_message_callback=on_message)
    logger.info(f"events consumer ready on queue '{QUEUE_EVENTS}'")
    try:
        channel.start_consuming()
    except Exception as e:
        logger.error(f"events consumer crashed: {e}", exc_info=True)


def start():
    recover_stuck_runs()
    recover_auto_runs()

    # Start the fast events consumer in a daemon thread so run_created /
    # run_completed are always processed immediately, even during long uploads.
    t = threading.Thread(target=_start_events_consumer, daemon=True, name="events-consumer")
    t.start()

    # TRE confirmations are polled here, outside the pipeline queue, so a run
    # waiting for the TRE does not block the next upload.
    threading.Thread(target=_verifier_loop, daemon=True, name="verifier").start()

    logger.info("connecting to RabbitMQ (pipeline)...")
    connection = _connect_rabbitmq("pipeline")
    channel    = connection.channel()
    channel.queue_declare(queue=QUEUE_PIPELINE, durable=True)

    # prefetch_count=1: process one pipeline task at a time — prevents
    # concurrent uploads which would overwhelm the network and storage.
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_PIPELINE, on_message_callback=on_pipeline_message)

    logger.info(f"waiting for messages on queues '{QUEUE_EVENTS}' (thread) and '{QUEUE_PIPELINE}' (main). press Ctrl+C to stop.")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()

    connection.close()


if __name__ == "__main__":
    start()
