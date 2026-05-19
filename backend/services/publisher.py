import json
import os
import pika

from core.logger import get_logger

logger = get_logger("publisher")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME   = "runs"

def _get_channel():
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL)) # open TCP connection to RabbitMQ
    channel    = connection.channel() # open a channel on the connection 

    # durable=True means the queue itself survives a RabbitMQ restart. Without this, if RabbitMQ crashes, the queue definition is gone
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    return connection, channel


def publish(event: str, name: str, sequencer_uuid: str):
    """
    Sends a message to the RabbitMQ "runs" queue.
    """
    message = json.dumps({
        "event":          event, # "run_created" | "run_completed" | "run_failed" | "run_moved"
        "name":           name, # "run_2026_04_15"
        "sequencer_uuid": str(sequencer_uuid), # "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    })

    # Open TCP connection to RabbitMQ, send message, then close connection.
    connection, channel = _get_channel()

    # Direct, Topic, Fanout, Headers
    channel.basic_publish(
        exchange="",          # Direct Exchange
        routing_key=QUEUE_NAME, # runs
        body=message, # JSON string containing event info
        properties=pika.BasicProperties(
            delivery_mode=2,  # makes the message persistent & if RabbitMQ restarts, the message is not lost / # 1=transient (lost on restart), 2=persistent (survives restart)
        )
    )

    connection.close()
    logger.info(f"sent → {message}")
