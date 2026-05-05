import os
import sys
import json
import time
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pika

import db.base  # registers all models so SQLAlchemy can resolve all relationships
from db.session import SESSION_LOCAL
from db.models.sequencers import Sequencers
from db.repositories.runs import create_run, update_run_status
from db.repositories.runs_status_history import add_run_status_history
from services.zipper import create_zip
from services.tre import send_to_tre, delete_zip
from core.logger import get_logger

logger = get_logger("worker")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME   = "runs"


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
      - auto   → immediately publish run_zip_requested so the worker
                 continues the pipeline without waiting
      - manual → stop here; a button in the UI will trigger the next step
    """
    logger.info(f"run_completed → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="running_finished", db=db)
        add_run_status_history(run_uuid=run.uuid, status="running_finished", db=db)
        logger.info(f"status updated to 'running_finished' for run '{name}'")

        sequencer = get_sequencer(sequencer_uuid)
        if not sequencer:
            logger.error(f"sequencer {sequencer_uuid} not found — cannot determine sent_to_tre setting")
            return

        if sequencer.sent_to_tre == "auto":
            logger.info(f"sent_to_tre=auto — publishing run_zip_requested for '{name}'")
            from services.publisher import publish
            publish("run_zip_requested", name, sequencer_uuid)
        else:
            logger.info(f"sent_to_tre=manual — waiting for user to trigger zipping for '{name}'")

    except Exception as e:
        logger.error(f"failed to handle run_completed for '{name}': {e}", exc_info=True)
    finally:
        db.close()


def handle_run_zip_requested(name: str, sequencer_uuid):
    """
    Triggered either automatically (sent_to_tre=auto) or by a manual button click.
    1. Zip the run folder                → status: zipping
    2. Upload zip to TRE S3 (stub)      → status: moving → confirmation
    3. If delete_after_confirmation=auto → publish run_delete_requested immediately
       If manual                         → wait for button click
    """
    logger.info(f"run_zip_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        # step 1 — zipping
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="zipping", db=db)
        add_run_status_history(run_uuid=run.uuid, status="zipping", db=db)
        logger.info(f"status updated to 'zipping' for run '{name}'")

        sequencer = get_sequencer(sequencer_uuid)
        if not sequencer:
            logger.error(f"sequencer {sequencer_uuid} not found — cannot zip run '{name}'")
            return

        zip_path = create_zip(run_name=name, sequencer_location=sequencer.location)
        logger.info(f"zip created at {zip_path}")

        # step 2 — moving to TRE
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="moving", db=db)
        add_run_status_history(run_uuid=run.uuid, status="moving", db=db)
        logger.info(f"status updated to 'moving' for run '{name}'")

        send_to_tre(zip_path)
        logger.info(f"zip sent to TRE (stub) for run '{name}'")

        # step 3 — waiting for delete confirmation
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="confirmation", db=db)
        add_run_status_history(run_uuid=run.uuid, status="confirmation", db=db)
        logger.info(f"status updated to 'confirmation' for run '{name}'")

        if sequencer.delete_after_confirmation == "auto":
            logger.info(f"delete_after_confirmation=auto — publishing run_delete_requested for '{name}'")
            from services.publisher import publish
            publish("run_delete_requested", name, sequencer_uuid)
        else:
            logger.info(f"delete_after_confirmation=manual — waiting for user to confirm delete for '{name}'")

    except Exception as e:
        logger.error(f"failed during zip/move for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="zip_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="zip_failed", db=db)
        except Exception:
            pass
    finally:
        db.close()


def handle_run_delete_requested(name: str, sequencer_uuid):
    """
    Triggered either automatically (delete_after_confirmation=auto) or by a manual button click.
    Deletes the local zip file (stub) and marks the run as completed.
    """
    logger.info(f"run_delete_requested → name={name} sequencer_uuid={sequencer_uuid}")
    db = SESSION_LOCAL()
    try:
        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="deleting", db=db)
        add_run_status_history(run_uuid=run.uuid, status="deleting", db=db)
        logger.info(f"status updated to 'deleting' for run '{name}'")

        sequencer = get_sequencer(sequencer_uuid)
        if sequencer:
            zip_path = f"{sequencer.location}/{name}/{name}.zip"
            delete_zip(zip_path)
            logger.info(f"zip deleted (stub) for run '{name}'")

        run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="completed", db=db)
        add_run_status_history(run_uuid=run.uuid, status="completed", db=db)
        logger.info(f"status updated to 'completed' for run '{name}'")

    except Exception as e:
        logger.error(f"failed during delete for run '{name}': {e}", exc_info=True)
        try:
            run = update_run_status(name=name, sequencer_uuid=sequencer_uuid, new_status="delete_failed", db=db)
            add_run_status_history(run_uuid=run.uuid, status="delete_failed", db=db)
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

        elif event == "run_zip_requested":
            handle_run_zip_requested(name=name, sequencer_uuid=sequencer_uuid)

        elif event == "run_delete_requested":
            handle_run_delete_requested(name=name, sequencer_uuid=sequencer_uuid)

        else:
            logger.warning(f"unknown event: {event}")

    except Exception as e:
        logger.error(f"failed to process message: {e}", exc_info=True)

    finally:
        # ack tells RabbitMQ "I processed this message, remove it from the queue"
        # without ack, RabbitMQ keeps the message and re-delivers it if the worker restarts
        channel.basic_ack(delivery_tag=method.delivery_tag)


def start():
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
