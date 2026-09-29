import json
import os
import pika

from core.logger import get_logger

logger = get_logger("publisher")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

# Two queues: fast watcher events vs slow pipeline tasks.
# This ensures run_created/run_completed are always processed immediately,
# even when the worker is busy with a multi-hour upload.
QUEUE_EVENTS   = "runs_events"    # run_created, run_completed
QUEUE_PIPELINE = "runs_pipeline"  # checksum, upload, verify

_EVENT_QUEUES = {
    "run_created":              QUEUE_EVENTS,
    "run_completed":            QUEUE_EVENTS,
    "run_checksum_requested":   QUEUE_PIPELINE,
    "run_upload_requested":     QUEUE_PIPELINE,
    "run_verify_requested":     QUEUE_PIPELINE,
    "run_rechecksum_requested": QUEUE_PIPELINE,
    "run_directory_upload_requested": QUEUE_PIPELINE,
}


def publish(event: str, name: str, sequencer_uuid: str, **extra):
    """
    Sends a message to the appropriate RabbitMQ queue based on event type.
    Watcher events (run_created, run_completed) go to runs_events so they
    are processed immediately even while a long upload is in progress.
    Pipeline tasks go to runs_pipeline.
    extra keyword fields (e.g. directory=...) are added to the message body.
    """
    queue = _EVENT_QUEUES.get(event, QUEUE_PIPELINE)
    message = json.dumps({
        "event":          event,
        "name":           name,
        "sequencer_uuid": str(sequencer_uuid),
        **extra,
    })
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel    = connection.channel()
    channel.queue_declare(queue=queue, durable=True)
    channel.basic_publish(
        exchange="",
        routing_key=queue,
        body=message,
        properties=pika.BasicProperties(delivery_mode=2),
    )
    connection.close()
    logger.info(f"sent → {message}")
