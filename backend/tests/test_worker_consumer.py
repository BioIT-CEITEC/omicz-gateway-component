"""
The pipeline consumer must not block pika's connection thread: long tasks run
in their own thread and the ack is handed back via add_callback_threadsafe.
"""
import json
import os
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import worker


class FakeChannel:
    def __init__(self):
        self.is_open = True
        self.acked = []
        self.nacked = []
        self.prefetch = None
        self.calls = []
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

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))

    def basic_qos(self, prefetch_count, global_qos=False):
        self.prefetch = prefetch_count
        self.calls.append(("qos", prefetch_count, global_qos))


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


def _body(name, event="run_checksum_requested", **extra):
    return json.dumps({"event": event, "name": name, "sequencer_uuid": "s-1", **extra}).encode()


@pytest.mark.parametrize("setting", ["pipeline_parallel_runs", "pipeline_parallel_checksums"])
def test_limit_follows_setting_while_slots_are_busy(monkeypatch, setting):
    """The setting is re-read on a timer, not only when a message arrives (none arrives while all slots are busy)."""
    value = {"n": 1}
    monkeypatch.setattr(worker, "get_setting_int", lambda key, default: value["n"] if key == setting else default)
    timers = []
    connection = SimpleNamespace(call_later=lambda delay, cb: timers.append((delay, cb)))
    ch = FakeChannel()
    worker._watch_limit(connection, ch, setting)
    assert timers[-1][0] == worker.PARALLEL_RUNS_CHECK_INTERVAL
    # a channel-wide limit: RabbitMQ applies it at once and counts every task running on the channel
    assert ch.calls == [("qos", 1, True)]
    timers[-1][1]()                      # unchanged: not sent again
    assert len(ch.calls) == 1
    value["n"] = 2
    timers[-1][1]()                      # the timer fires on the connection thread
    assert ch.prefetch == 2
    assert ch.calls[1:] == [("qos", 2, True)]
    assert len(timers) == 3              # and schedules the next check


def test_checksums_have_their_own_queue():
    """A finished run is hashed while other runs upload; only its upload waits in the pipeline queue."""
    from services import publisher
    assert publisher._EVENT_QUEUES["run_checksum_requested"] == worker.QUEUE_CHECKSUM
    assert publisher._EVENT_QUEUES["run_rechecksum_requested"] == worker.QUEUE_CHECKSUM
    for event in ("run_upload_requested", "run_verify_requested", "run_directory_upload_requested"):
        assert publisher._EVENT_QUEUES[event] == worker.QUEUE_PIPELINE
    assert publisher.QUEUE_CHECKSUM == worker.QUEUE_CHECKSUM


def test_guard_spans_both_queues(monkeypatch):
    """A run's checksum (checksum queue) waits while one of its folders uploads (pipeline queue)."""
    release = threading.Event()
    requeued = []
    monkeypatch.setattr(worker, "dispatch", lambda body: release.wait(5))
    monkeypatch.setattr(worker, "BUSY_RUN_REQUEUE_DELAY", 0)
    monkeypatch.setattr(worker, "_requeue", lambda body: requeued.append(json.loads(body)["event"]))
    upload_ch, checksum_ch = FakeChannel(), FakeChannel()   # two connections, one process
    worker.on_pipeline_message(upload_ch, SimpleNamespace(delivery_tag=1), None,
                               _body("RUN_X", "run_directory_upload_requested", directory="Data"))
    try:
        worker.on_pipeline_message(checksum_ch, SimpleNamespace(delivery_tag=1), None, _body("RUN_X"))
        assert checksum_ch.scheduled.wait(5)
        assert requeued == ["run_checksum_requested"]
    finally:
        release.set()
    assert upload_ch.scheduled.wait(5)


def test_two_runs_run_at_the_same_time(monkeypatch):
    """With two slots, a second run starts while the first is still running."""
    started = {name: threading.Event() for name in ("RUN_A", "RUN_B")}
    release = threading.Event()

    def blocking_dispatch(body):
        started[json.loads(body)["name"]].set()
        release.wait(5)

    monkeypatch.setattr(worker, "dispatch", blocking_dispatch)
    ch_a, ch_b = FakeChannel(), FakeChannel()
    worker.on_pipeline_message(ch_a, SimpleNamespace(delivery_tag=1), None, _body("RUN_A"))
    worker.on_pipeline_message(ch_b, SimpleNamespace(delivery_tag=2), None, _body("RUN_B"))
    try:
        assert started["RUN_A"].wait(5)
        assert started["RUN_B"].wait(5)
    finally:
        release.set()
    assert ch_a.scheduled.wait(5) and ch_b.scheduled.wait(5)


def test_second_job_of_a_busy_run_goes_to_the_back_of_the_queue(monkeypatch):
    """The final checksum must not start while a directory of the same run is still uploading."""
    release = threading.Event()
    calls, requeued = [], []

    def dispatch(body):
        calls.append(json.loads(body)["event"])
        release.wait(5)

    monkeypatch.setattr(worker, "dispatch", dispatch)
    monkeypatch.setattr(worker, "BUSY_RUN_REQUEUE_DELAY", 0)
    monkeypatch.setattr(worker, "_requeue", lambda body: requeued.append(json.loads(body)))
    ch_dir, ch_sum = FakeChannel(), FakeChannel()
    worker.on_pipeline_message(ch_dir, SimpleNamespace(delivery_tag=1), None,
                               _body("RUN_A", "run_directory_upload_requested", directory="DIR1"))
    try:
        worker.on_pipeline_message(ch_sum, SimpleNamespace(delivery_tag=2), None, _body("RUN_A"))
        assert ch_sum.scheduled.wait(5)
        ch_sum.run_scheduled()
        assert ch_sum.acked == [2]                       # slot freed for other runs
        assert [m["event"] for m in requeued] == ["run_checksum_requested"]
        assert calls == ["run_directory_upload_requested"]
    finally:
        release.set()
    assert ch_dir.scheduled.wait(5)
    ch_dir.run_scheduled()
    assert worker._claim_run(("RUN_A", "s-1"))           # released after the job ended
    worker._release_run(("RUN_A", "s-1"))


def test_failed_requeue_hands_the_message_back(monkeypatch):
    monkeypatch.setattr(worker, "BUSY_RUN_REQUEUE_DELAY", 0)
    monkeypatch.setattr(worker, "_requeue", lambda body: (_ for _ in ()).throw(ConnectionError("down")))
    key = ("RUN_C", "s-1")
    assert worker._claim_run(key)
    try:
        ch = FakeChannel()
        worker.on_pipeline_message(ch, SimpleNamespace(delivery_tag=5), None, _body("RUN_C"))
        assert ch.scheduled.wait(5)
        ch.run_scheduled()
        assert ch.acked == [] and ch.nacked == [(5, True)]
    finally:
        worker._release_run(key)


def test_requeue_keeps_extra_fields(monkeypatch):
    sent = []
    import services.publisher as publisher
    monkeypatch.setattr(publisher, "publish", lambda event, name, seq, **extra: sent.append((event, name, seq, extra)))
    worker._requeue(_body("RUN_A", "run_directory_upload_requested", directory="DIR1"))
    assert sent == [("run_directory_upload_requested", "RUN_A", "s-1", {"directory": "DIR1"})]


def test_upload_text_says_when_s3_is_still_finishing_files():
    gb = 1024 ** 3
    assert worker._upload_text(1, 4, 1 * gb, 4 * gb) == "1 / 4 files · 1.0 GB / 4.0 GB"
    # every byte written, two files not confirmed by S3 yet
    assert worker._upload_text(2, 4, 4 * gb, 4 * gb) == "2 / 4 files · 4.0 GB / 4.0 GB · S3 finishing 2 files"
    assert worker._upload_text(3, 4, 4 * gb, 4 * gb).endswith("S3 finishing 1 file")
    assert worker._upload_text(4, 4, 4 * gb, 4 * gb) == "4 / 4 files · 4.0 GB / 4.0 GB"


def _run_folder(tmp_path):
    run = tmp_path / "RUN_D"
    (run / "Data").mkdir(parents=True)
    (run / "Data" / "a.bcl").write_bytes(b"x" * 5000)
    (run / "RunInfo.xml").write_bytes(b"<r/>")
    manifest = run / "abc.CHECKSUM"
    manifest.write_bytes(b"d" * 65)
    st = os.stat(run / "Data" / "a.bcl")
    return run, manifest, {"Data/a.bcl": (st.st_size, st.st_mtime_ns)}


def test_bytes_left_counts_unsent_files_and_the_manifest(tmp_path, monkeypatch):
    run, manifest, sent = _run_folder(tmp_path)
    monkeypatch.setattr(worker.dir_stability, "uploaded_files", lambda run_uuid, db: sent)
    # Data/ went early (directory stability): only RunInfo.xml and the .CHECKSUM are left
    assert worker._bytes_left_to_send("u", str(run), [], str(manifest), None) == 4 + 65
    # nothing sent yet (signal rule, or a retry that reused the .CHECKSUM): everything is left
    monkeypatch.setattr(worker.dir_stability, "uploaded_files", lambda run_uuid, db: {})
    assert worker._bytes_left_to_send("u", str(run), [], str(manifest), None) == 5000 + 4 + 65


@pytest.mark.parametrize("limit_mb,sent_early,expect", [
    (1024, True,  "now"),     # only leftovers: upload at once, no waiting for a slot
    (0,    True,  "queue"),   # fast lane switched off
    (1024, False, "now"),     # a small run that fits under the limit
])
def test_after_checksum_small_leftovers_skip_the_upload_queue(tmp_path, monkeypatch, limit_mb, sent_early, expect):
    run, manifest, sent = _run_folder(tmp_path)
    monkeypatch.setattr(worker.dir_stability, "uploaded_files", lambda run_uuid, db: sent if sent_early else {})
    monkeypatch.setattr(worker, "get_setting_int", lambda key, default: limit_mb if key == "upload_fast_lane_mb" else default)
    calls = []
    monkeypatch.setattr(worker, "handle_run_upload_requested", lambda name, seq: calls.append("now"))
    import services.publisher as publisher
    monkeypatch.setattr(publisher, "publish", lambda event, name, seq, **kw: calls.append("queue"))
    worker._continue_after_checksum("RUN_D", "s-1", "u", str(run), [], str(manifest), None)
    assert calls == [expect]


def test_after_checksum_large_upload_waits_for_a_slot(tmp_path, monkeypatch):
    run, manifest, _ = _run_folder(tmp_path)
    monkeypatch.setattr(worker.dir_stability, "uploaded_files", lambda run_uuid, db: {})
    monkeypatch.setattr(worker, "_bytes_left_to_send", lambda *a: 10 * 1024 ** 4)   # 10 TB
    monkeypatch.setattr(worker, "get_setting_int", lambda key, default: 1024 if key == "upload_fast_lane_mb" else default)
    calls = []
    monkeypatch.setattr(worker, "handle_run_upload_requested", lambda name, seq: calls.append("now"))
    import services.publisher as publisher
    monkeypatch.setattr(publisher, "publish", lambda event, name, seq, **kw: calls.append(event))
    worker._continue_after_checksum("RUN_D", "s-1", "u", str(run), [], str(manifest), None)
    assert calls == ["run_upload_requested"]


def test_next_step_is_sent_after_the_run_is_released(monkeypatch):
    """The upload published by a checksum job must not find its own run still busy."""
    seen = []
    import services.publisher as publisher
    monkeypatch.setattr(publisher, "publish",
                        lambda event, name, seq, **kw: seen.append((event, worker._claim_run((name, seq)))) or worker._release_run((name, seq)))
    monkeypatch.setattr(worker, "dispatch", lambda body: worker._publish_after_job("run_upload_requested", "RUN_N", "s-1"))
    ch = FakeChannel()
    worker.on_pipeline_message(ch, SimpleNamespace(delivery_tag=1), None, _body("RUN_N"))
    assert ch.scheduled.wait(5)
    assert seen == [("run_upload_requested", True)]     # sent once, with the run already free


def test_background_consumer_reconnects_after_any_disconnect(monkeypatch):
    """A RabbitMQ restart or a long outage must not end the events/checksum consumer for good."""
    attempts, setups = [], []

    class Chan:
        def start_consuming(self):
            raise ConnectionError("broker forced connection closure")   # RabbitMQ restarted

    class Conn:
        def channel(self):
            return Chan()

    def connect(label):
        attempts.append(label)
        if len(attempts) == 1:
            raise SystemExit(1)          # _connect_rabbitmq gave up after its retries
        if len(attempts) == 4:
            raise KeyboardInterrupt      # end the test
        return Conn()

    monkeypatch.setattr(worker, "_connect_rabbitmq", connect)
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    with pytest.raises(KeyboardInterrupt):
        worker._consume_forever("events", lambda conn, ch: setups.append(conn))
    assert attempts == ["events"] * 4    # kept trying after SystemExit and after each lost connection
    assert len(setups) == 2              # the queue and callback are set up again on every new connection
