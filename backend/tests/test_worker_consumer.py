"""
The pipeline consumer must not block pika's connection thread: long tasks run
in their own thread and the ack is handed back via add_callback_threadsafe.
"""
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import worker


class FakeChannel:
    def __init__(self):
        self.is_open = True
        self.acked = []
        self.scheduled = threading.Event()
        self.connection = SimpleNamespace(add_callback_threadsafe=self._schedule)
        self._callback = None

    def _schedule(self, cb):
        self._callback = cb
        self.scheduled.set()

    def run_scheduled(self):
        """What start_consuming() does on the connection thread."""
        self._callback()

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)


def test_pipeline_task_runs_off_thread_and_acks_after(monkeypatch):
    release = threading.Event()
    seen = {}

    def slow_dispatch(body):
        seen["thread"] = threading.current_thread().name
        release.wait(5)

    monkeypatch.setattr(worker, "dispatch", slow_dispatch)
    ch = FakeChannel()

    worker.on_pipeline_message(ch, SimpleNamespace(delivery_tag=7), None, b"{}")

    # callback returned immediately; task still running, nothing acked yet
    assert not ch.scheduled.wait(0.2)
    assert ch.acked == []

    release.set()
    assert ch.scheduled.wait(5)
    assert seen["thread"] == "pipeline-task"
    assert ch.acked == []          # ack only happens on the connection thread
    ch.run_scheduled()
    assert ch.acked == [7]


def test_pipeline_task_acks_even_when_handler_raises(monkeypatch):
    monkeypatch.setattr(worker, "dispatch", lambda body: (_ for _ in ()).throw(RuntimeError("boom")))
    ch = FakeChannel()
    worker.on_pipeline_message(ch, SimpleNamespace(delivery_tag=3), None, b"{}")
    assert ch.scheduled.wait(5)
    ch.run_scheduled()
    assert ch.acked == [3]


def test_no_ack_on_closed_channel(monkeypatch):
    monkeypatch.setattr(worker, "dispatch", lambda body: None)
    ch = FakeChannel()
    worker.on_pipeline_message(ch, SimpleNamespace(delivery_tag=9), None, b"{}")
    assert ch.scheduled.wait(5)
    ch.is_open = False
    ch.run_scheduled()
    assert ch.acked == []
