import json
import os
import pika

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME   = "runs"


def _get_channel():
    """
    Opens a connection to RabbitMQ and returns a channel.

    Think of it like this:
        connection = the phone line to RabbitMQ
        channel    = the actual conversation on that line

    We use a fresh connection per publish because this runs in a
    background watcher process (not an async web server).
    """
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel    = connection.channel()

    # declare_queue is idempotent — safe to call every time
    # if the queue already exists, RabbitMQ just ignores this call
    # durable=True means the queue itself survives a RabbitMQ restart. Without this, if RabbitMQ crashes, the queue definition is gone
    # queue name is "runs" — the worker listens to this queue for messages about run events
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    return connection, channel


def publish(event: str, name: str, sequencer_uuid: str):
    """
    Sends a message to the RabbitMQ "runs" queue.

    The worker on the other end will receive this and act on it.

    Message format:
    {
        "event":          "run_created" | "run_completed" | "run_failed" | "run_moved",
        "name":           "run_2026_04_15",
        "sequencer_uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    }
    """
    message = json.dumps({
        "event":          event,
        "name":           name,
        "sequencer_uuid": str(sequencer_uuid),
    })

    # Open TCP connection to RabbitMQ, send message, then close connection.
    connection, channel = _get_channel()

    channel.basic_publish(
        exchange="",          # default exchange — routes directly to the queue by name (Using "" means the default (direct) exchange)
        routing_key=QUEUE_NAME,
        body=message, # JSON string containing event info
        properties=pika.BasicProperties(
            delivery_mode=2,  # makes the message persistent
                              # if RabbitMQ restarts, the message is not lost
        )
    )

    connection.close()
    print(f"[publisher] sent → {message}")
