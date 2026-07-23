import os
import sys
import json
import time
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

from services.checksum import create_checksum_file, find_file_by_hash, _fmt_bytes
from services.tre import send_to_tre, verify_checksum_on_s3, VERIFY_RETRIES
from core.logger import get_logger

logger = get_logger("worker")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME   = "runs"


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


def _make_progress_callback(run_uuid):
    """Returns a callback that writes checksumming progress to the run's progress column."""
    def callback(done: int, total: int, bytes_done: int, total_bytes: int):
        text = f"{done} / {total} files · {_fmt_bytes(bytes_done)} / {_fmt_bytes(total_bytes)}"
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


def get_sequencer(sequencer_uuid) -> Sequencers | None:
    """
    Fetches the full sequencer row from the DB.
    Used to read location, sent_to_tre, and delete_after_confirmation.
    """
    db = SESSION_LOCAL()
    try:
        return db.query(Sequencers).filter(Sequencers.uuid == sequencer_uuid).first()
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
        if existing and existing.status in ("checksumming", "moving", "completed", "move_failed"):
            logger.warning(f"run_completed ignored for '{name}' — already in status '{existing.status}'")
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

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="checksumming", db=db)
        add_run_status_history(run_uuid=run.uuid, status="checksumming", db=db)
        logger.info(f"status updated to 'checksumming' for run '{name}'")

        create_checksum_file(run_name=name, sequencer_location=sequencer.location, exclusions=sequencer.exclusions or [], on_progress=_make_progress_callback(run.uuid))

        # checksumming done — set queued while waiting for upload slot, clear progress
        run_obj = db.query(Runs).filter(Runs.uuid == run.uuid).first()
        if run_obj:
            run_obj.status   = "queued"
            run_obj.progress = None
            db.commit()
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

    # ── step 1: upload ────────────────────────────────────────────────────────
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="moving", db=db)
        run.progress = "scanning files…"
        db.commit()
        add_run_status_history(run_uuid=run.uuid, status="moving", db=db)
        logger.info(f"status updated to 'moving' for run '{name}'")

        send_to_tre(run_name=name, sequencer_location=sequencer.location, sequencer_slug=sequencer.slug, exclusions=sequencer.exclusions or [], on_progress=_make_progress_callback(run.uuid))
        logger.info(f"run folder uploaded to S3 for run '{name}'")

    except Exception as e:
        logger.error(f"[upload] FAILED for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="move_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="move_failed", db=db, detail=str(e))
        except Exception:
            pass
        db.close()
        return

    # ── step 2: verify ────────────────────────────────────────────────────────
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="verifying", db=db)
        add_run_status_history(run_uuid=run.uuid, status="verifying", db=db)
        logger.info(f"status updated to 'verifying' for run '{name}'")

        run_folder = os.path.join(sequencer.location, name)
        checksum_files = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
        if not checksum_files:
            raise Exception("no .CHECKSUM file found in run folder — cannot verify")
        checksum_filename = os.path.basename(checksum_files[0])
        logger.info(f"[verify] using checksum file: {checksum_filename}")

        verified, tre_error = verify_checksum_on_s3(checksum_filename)
        if not verified:
            raise Exception(resolve_verify_detail(tre_error, run_folder, VERIFY_RETRIES))

    except Exception as e:
        logger.error(f"[verify] FAILED for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="verify_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="verify_failed", db=db, detail=str(e))
        except Exception:
            pass
        db.close()
        return

    # ── step 3: done ──────────────────────────────────────────────────────────
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="completed", db=db)
        add_run_status_history(run_uuid=run.uuid, status="completed", db=db)
        logger.info(f"status updated to 'completed' for run '{name}'")
    except Exception as e:
        logger.error(f"failed to mark run '{name}' as completed: {e}", exc_info=True)
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

        run_folder = os.path.join(sequencer.location, name)
        existing = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
        for f in existing:
            os.remove(f)
            logger.info(f"deleted old checksum file: {os.path.basename(f)}")

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="checksumming", db=db)
        add_run_status_history(run_uuid=run.uuid, status="checksumming", db=db)
        logger.info(f"status updated to 'checksumming' for run '{name}'")

        create_checksum_file(run_name=name, sequencer_location=sequencer.location, exclusions=sequencer.exclusions or [], on_progress=_make_progress_callback(run.uuid))

        # checksumming done — set queued while waiting for upload slot, clear progress
        run_obj = db.query(Runs).filter(Runs.uuid == run.uuid).first()
        if run_obj:
            run_obj.status   = "queued"
            run_obj.progress = None
            db.commit()
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
    Triggered when retrying from verify_failed.
    Skips checksum and upload — goes straight to verification only.
    """
    logger.info(f"run_verify_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()

    sequencer = get_sequencer(sequencer_uuid)
    if not sequencer:
        logger.error(f"sequencer {sequencer_uuid} not found — cannot verify run '{name}'")
        db.close()
        return

    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="verifying", db=db)
        add_run_status_history(run_uuid=run.uuid, status="verifying", db=db)
        logger.info(f"status updated to 'verifying' for run '{name}'")

        run_folder = os.path.join(sequencer.location, name)
        checksum_files = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
        if not checksum_files:
            raise Exception("no .CHECKSUM file found in run folder — cannot verify")
        checksum_filename = os.path.basename(checksum_files[0])
        logger.info(f"[verify] using checksum file: {checksum_filename}")

        verified, tre_error = verify_checksum_on_s3(checksum_filename)
        if not verified:
            raise Exception(resolve_verify_detail(tre_error, run_folder, VERIFY_RETRIES))

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="completed", db=db)
        add_run_status_history(run_uuid=run.uuid, status="completed", db=db)
        logger.info(f"status updated to 'completed' for run '{name}'")

    except Exception as e:
        logger.error(f"[verify] FAILED for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="verify_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="verify_failed", db=db, detail=str(e))
        except Exception:
            pass
    finally:
        db.close()


def on_message(channel, method, properties, body):
    """
    Called by pika every time a message arrives from RabbitMQ.

    Parameters:
        channel    → the RabbitMQ channel (we use it to ack the message)
        method     → delivery metadata (we need method.delivery_tag to ack)
        properties → message properties (unused here)
        body       → the raw message bytes
    """
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

        else:
            logger.warning(f"unknown event: {event}")

    except Exception as e:
        logger.error(f"failed to process message: {e}", exc_info=True)

    finally:
        # ack tells RabbitMQ "I processed this message, remove it from the queue"
        # without ack, RabbitMQ keeps the message and re-delivers it if the worker restarts
        channel.basic_ack(delivery_tag=method.delivery_tag)


def recover_stuck_runs():
    """
    On worker startup, find any runs stuck in intermediate states
    (checksumming / moving / verifying) and mark them failed.
    These indicate the worker crashed mid-processing.
    """
    STUCK_STATUSES = ["checksumming", "moving", "verifying"]
    db = SESSION_LOCAL()
    try:
        stuck = db.query(Runs).filter(Runs.status.in_(STUCK_STATUSES)).all()
        for run in stuck:
            logger.warning(f"recovering stuck run '{run.name}' (status={run.status}) — marking as failed")
            old_status = run.status
            run.status = "failed"
            run.progress = None
            db.flush()
            add_run_status_history(
                run_uuid=run.uuid,
                status="failed",
                db=db,
                detail=f"Worker restarted while run was in '{old_status}' — use Retry to resume",
            )
        db.commit()
        if stuck:
            logger.info(f"recovered {len(stuck)} stuck run(s)")
    except Exception as e:
        logger.error(f"failed to recover stuck runs: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def start():
    recover_stuck_runs()
    logger.info("connecting to RabbitMQ...")
    for attempt in range(1, 11):
        try:
            connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            break
        except Exception as e:
            logger.warning(f"attempt {attempt}/10 failed to connect to RabbitMQ: {e} — retrying in 5s...")
            time.sleep(5)
    else:
        logger.error("could not connect to RabbitMQ after 10 attempts, exiting.")
        sys.exit(1)
    channel    = connection.channel()

    # declare the same queue as the publisher — safe to call multiple times
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    # prefetch_count=1 means: only give me one message at a time
    # don't send the next message until I ack the current one
    # this prevents the worker from being overwhelmed
    # Without this, RabbitMQ could push many messages at once and the worker would start processing them all in parallel — dangerous when zipping large BAM files.
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)

    logger.info(f"waiting for messages on queue '{QUEUE_NAME}'. press Ctrl+C to stop.")
    try:
        # blocks here — runs forever, calling on_message for each new message
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()

    connection.close()


if __name__ == "__main__":
    start()
