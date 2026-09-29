import os
import sys
import time
import threading
from datetime import datetime

from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

# allow imports from the backend folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # registers all models so SQLAlchemy can resolve relationships
from db.session import SESSION_LOCAL
from db.models.sequencers import Sequencers
from db.models.runs import Runs
from db.models.runs_status_history import RunsStatusHistory
from services.publisher import publish
from services import dir_stability
from core.logger import get_logger
from db.repositories.settings import get_setting_int

logger = get_logger("watcher")


class RunEventHandler(FileSystemEventHandler):
    """
    Handles filesystem events for a single sequencer location.

    Directory structure we're watching:
        sequencer.location/                  ← we watch this
            run_2026_04_15/                  ← depth 1: new run folder
                **_complete.txt              ← depth 2: completion signal (signal method only)
    """

    def __init__(self, sequencer, stability_tracker: dict):
        self.sequencer         = sequencer
        self.location          = sequencer.location
        self.completion_method = sequencer.type.completion_method if sequencer.type else "signal"
        self.stability_tracker = stability_tracker  # shared with main loop (GIL-safe dict ops)

        # store the completion signal info from the sequencer type
        # so we don't need to re-query DB on every event
        if sequencer.type:
            self.signal          = sequencer.type.completion_signal
            self.signal_match    = sequencer.type.signal_match
            self.stability_files = sequencer.type.stability_files or []
        else:
            self.signal          = None
            self.signal_match    = None
            self.stability_files = []

        # pending timers: run_name → threading.Timer
        # folders wait RUN_DETECTION_DELAY seconds before being registered,
        # so OS default names ("New Folder") get a chance to be renamed first
        self._pending = {}
        self._lock    = threading.Lock()

    def _register_run(self, run_name):
        """Called after RUN_DETECTION_DELAY seconds. Publishes run_created if folder still exists."""
        with self._lock:
            self._pending.pop(run_name, None)
        run_folder = os.path.join(self.location, run_name)
        if not os.path.isdir(run_folder):
            logger.info(f"folder '{run_name}' no longer exists after delay — skipping")
            return
        logger.info(f"new run detected: {run_name} on sequencer {self.sequencer.name}")
        publish("run_created", run_name, self.sequencer.uuid)

    def on_created(self, event):
        # The observer uses recursive=False so only top-level directory events fire here.
        # We only care about new run folders (directories) directly inside the location.
        if not event.is_directory:
            return

        relative = os.path.relpath(event.src_path, self.location)
        parts    = relative.split(os.sep)

        if len(parts) != 1:
            return

        run_name = parts[0]
        delay = get_setting_int("run_detection_delay", _RUN_DETECTION_DELAY_DEFAULT)
        logger.info(f"folder detected: '{run_name}' — waiting {delay}s before registering")
        with self._lock:
            # cancel any existing timer for this name (safety guard)
            if run_name in self._pending:
                self._pending[run_name].cancel()
            t = threading.Timer(delay, self._register_run, args=[run_name])
            self._pending[run_name] = t
            t.start()

    def on_deleted(self, event):
        """Cancel pending timer if a folder is renamed/deleted before the delay expires."""
        relative = os.path.relpath(event.src_path, self.location)
        parts    = relative.split(os.sep)

        if len(parts) == 1 and event.is_directory:
            run_name = parts[0]
            with self._lock:
                if run_name in self._pending:
                    self._pending[run_name].cancel()
                    del self._pending[run_name]
                    logger.info(f"folder '{run_name}' was renamed/deleted before registering — cancelled")


def load_sequencers():
    """
    Query the DB for all active sequencers that have a location set.
    Loads the type relationship eagerly so we have signal info ready.
    Retries until the DB is reachable (handles startup race with Docker).
    """
    # Because maybe watcher start before DB is ready (e.g. in Docker), we retry the connection several times with a delay.
    for attempt in range(1, 11):
        try:
            db = SESSION_LOCAL()
            try:
                sequencers = (
                    db.query(Sequencers)
                    .filter(
                        Sequencers.is_deleted == False,
                        Sequencers.location != None,
                    )
                    .all()
                )
                # access .type here while session is open so it loads the relationship
                for s in sequencers:
                    _ = s.type
                return sequencers
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"attempt {attempt}/10 failed to connect to DB: {e} — retrying in 5s...")
            time.sleep(5)

    logger.error("could not connect to DB after 10 attempts, exiting.")
    sys.exit(1)


def query_sequencers():
    """
    Simple one-shot DB query for active sequencers with a location.
    Used by the polling loop — no retry (DB is already up by then).
    """
    db = SESSION_LOCAL()
    try:
        sequencers = (
            db.query(Sequencers)
            .filter(
                Sequencers.is_deleted == False,
                Sequencers.location != None,
            )
            .all()
        )
        for s in sequencers:
            _ = s.type  # load relationship while session is open
        return sequencers
    except Exception as e:
        logger.error(f"failed to query sequencers: {e}")
        return []
    finally:
        db.close()


def is_completed(run_folder: str, sequencer) -> bool:
    """
    Checks whether the completion signal file already exists inside a run folder.
    Used during the initial scan to determine status of pre-existing runs.
    Only applicable to the "signal" completion method.
    """
    if not sequencer.type:
        return False

    if sequencer.type.completion_method != "signal":
        return False

    signal       = sequencer.type.completion_signal
    signal_match = sequencer.type.signal_match

    for filename in os.listdir(run_folder):
        matched = (
            (signal_match == "exact"  and filename == signal) or
            (signal_match == "prefix" and filename.startswith(signal)) or
            (signal_match == "suffix" and filename.endswith(signal))
        )
        if matched:
            return True
    return False


def scan_existing_runs(sequencer):
    """
    On startup, scans the sequencer location for existing run folders.
    - Skips folders already stored in the DB
    - Inserts missing ones, inferring status from whether the completion signal exists
    """
    location = sequencer.location

    db = SESSION_LOCAL()
    try:
        added = 0
        skipped = 0
        to_complete = []

        for entry in os.scandir(location):
            # only interested in subdirectories (run folders)
            if not entry.is_dir():
                continue

            run_name = entry.name

            # check if this run is already in the DB
            existing = (
                db.query(Runs)
                .filter(Runs.name == run_name, Runs.sequencer_uuid == sequencer.uuid)
                .first()
            )

            if existing:
                # if already in DB but still "running", check if signal file arrived
                # while the watcher was down — if so, re-publish run_completed
                if existing.status == "running":
                    run_folder = os.path.join(location, run_name)
                    if is_completed(run_folder, sequencer):
                        logger.info(f"catch-up → '{run_name}' already has signal file, publishing run_completed")
                        publish("run_completed", run_name, sequencer.uuid)
                skipped += 1
                continue

            # Every backfilled run is inserted as "running". Runs that already have their
            # completion signal get run_completed AFTER the commit below, so the worker's
            # normal handler moves them to running_finished and applies sent_to_tre.
            # (Inserting them as running_finished and publishing before the commit made
            # the worker either miss the row or ignore the event — backlog never sent.)
            # For file/directory stability we can't tell on startup — the timers decide.
            run_folder  = os.path.join(location, run_name)
            completed   = is_completed(run_folder, sequencer)

            run = Runs(name=run_name, sequencer_uuid=sequencer.uuid, status="running")
            db.add(run)
            db.flush()  # assigns run.uuid before we reference it below
            db.add(RunsStatusHistory(run_uuid=run.uuid, status="running"))
            added += 1
            logger.info(f"backfill → {run_name} (completion signal present: {completed})")
            if completed:
                to_complete.append(run_name)

        db.commit()
        logger.info(f"scan done for '{sequencer.name}': {added} added, {skipped} skipped")

        # queue completion only now that the rows are committed and visible to the worker
        for run_name in to_complete:
            publish("run_completed", run_name, sequencer.uuid)

    finally:
        db.close()


def check_file_stability(sequencers: list, stability_tracker: dict):
    """
    For sequencers using the file_stability completion method:
    checks if the monitored files have stopped growing for the configured threshold.

    stability_tracker structure:
    {
        "sequencer-uuid": {
            "run_name": {
                "sizes": {"output.bam": 1048576, "reads.fastq.gz": 2097152},
                "stable_since": datetime(...)
            }
        }
    }
    """
    for sequencer in sequencers:
        if not sequencer.type or sequencer.type.completion_method != "file_stability":
            continue

        stability_files     = sequencer.type.stability_files or []
        threshold_minutes   = sequencer.type.stability_threshold_minutes or 10

        if not stability_files:
            logger.warning(f"sequencer '{sequencer.name}' uses file_stability but has no stability_files configured")
            continue

        seq_uuid = str(sequencer.uuid)
        if seq_uuid not in stability_tracker:
            stability_tracker[seq_uuid] = {}

        # query DB for runs currently in "running" status for this sequencer
        db = SESSION_LOCAL()
        try:
            runs = (
                db.query(Runs)
                .filter(
                    Runs.sequencer_uuid == sequencer.uuid,
                    Runs.status == "running",
                    Runs.is_deleted == False,
                )
                .all()
            )
        except Exception as e:
            logger.error(f"stability check: failed to query runs for '{sequencer.name}': {e}")
            continue
        finally:
            db.close()

        for run in runs:
            run_folder = os.path.join(sequencer.location, run.name)
            run_name   = run.name

            # check that all stability files are present before we start the timer
            current_sizes = {}
            all_present   = True
            for filename in stability_files:
                filepath = os.path.join(run_folder, filename)
                if not os.path.isfile(filepath):
                    all_present = False
                    logger.debug(f"stability check: '{filename}' not yet present in {run_name}")
                    break
                current_sizes[filename] = os.path.getsize(filepath)

            if not all_present:
                continue

            tracker = stability_tracker[seq_uuid]

            if run_name not in tracker:
                # first time we see all files present — record sizes and start the timer
                tracker[run_name] = {
                    "sizes":        current_sizes,
                    "stable_since": datetime.now(),
                }
                logger.info(f"stability tracking started for {run_name} — sizes: {current_sizes}")
                continue

            prev = tracker[run_name]

            if current_sizes != prev["sizes"]:
                # files are still growing — update snapshot and reset timer
                logger.info(f"stability check: {run_name} still growing — resetting timer")
                prev["sizes"]        = current_sizes
                prev["stable_since"] = datetime.now()
            else:
                # sizes unchanged — check if we've hit the threshold
                elapsed_minutes = (datetime.now() - prev["stable_since"]).total_seconds() / 60
                logger.debug(f"stability check: {run_name} stable for {elapsed_minutes:.1f}/{threshold_minutes} min")

                if elapsed_minutes >= threshold_minutes:
                    logger.info(f"run completed (file_stability): {run_name} on sequencer '{sequencer.name}'")
                    publish("run_completed", run_name, sequencer.uuid)
                    del tracker[run_name]


def check_directory_stability(sequencers: list):
    """
    For sequencers using the 'directory_stability' completion method:
    fingerprints each top-level directory of every 'running' run, sends quiet
    directories early and finalizes runs that stopped changing.
    State lives in run_directories / runs, so a watcher restart does not reset timers.
    See services/dir_stability.py.
    """
    for sequencer in sequencers:
        if not sequencer.type or sequencer.type.completion_method != "directory_stability":
            continue
        if not os.path.isdir(sequencer.location):
            continue

        db = SESSION_LOCAL()
        try:
            runs = (
                db.query(Runs)
                .filter(
                    Runs.sequencer_uuid == sequencer.uuid,
                    Runs.status == "running",
                    Runs.is_deleted == False,
                )
                .all()
            )
            for run in runs:
                try:
                    dir_stability.process_run(run, sequencer, db, publish)
                except Exception as e:
                    db.rollback()
                    logger.error(f"directory stability: error checking '{run.name}': {e}", exc_info=True)
        except Exception as e:
            logger.error(f"directory stability: failed to query runs for '{sequencer.name}': {e}")
        finally:
            db.close()


_signal_published: set = set()  # run UUIDs already published this process lifetime


def check_signal_files(sequencers: list):
    """
    For sequencers using the 'signal' completion method:
    polls each run folder that is still 'running' to see if the completion
    signal file has appeared.

    This replaces the depth-2 on_created handler that was removed when we
    switched the PollingObserver to recursive=False. Polling every ~10s gives
    the same responsiveness with none of the recursive-scan overhead.

    _signal_published tracks which run UUIDs have already had run_completed
    published this session, preventing repeated messages while the worker is
    busy. When the watcher restarts the set is cleared, but by then the worker
    will have updated the run status away from 'running' so the query won't
    return them again.
    """
    for sequencer in sequencers:
        if not sequencer.type or sequencer.type.completion_method != "signal":
            continue
        if not sequencer.type.completion_signal:
            continue
        if not os.path.isdir(sequencer.location):
            continue

        db = SESSION_LOCAL()
        try:
            runs = (
                db.query(Runs)
                .filter(
                    Runs.sequencer_uuid == sequencer.uuid,
                    Runs.status == "running",
                    Runs.is_deleted == False,
                )
                .all()
            )
        except Exception as e:
            logger.error(f"signal check: failed to query runs for '{sequencer.name}': {e}")
            continue
        finally:
            db.close()

        for run in runs:
            if run.uuid in _signal_published:
                continue
            run_folder = os.path.join(sequencer.location, run.name)
            try:
                if is_completed(run_folder, sequencer):
                    logger.info(f"run completed (signal check): {run.name} on sequencer '{sequencer.name}'")
                    _signal_published.add(run.uuid)
                    publish("run_completed", run.name, sequencer.uuid)
            except Exception as e:
                logger.error(f"signal check: error checking '{run.name}': {e}")


_SEQUENCER_CHECK_INTERVAL_DEFAULT = 60
_RUN_DETECTION_DELAY_DEFAULT      = 15
_RUN_SCAN_INTERVAL_DEFAULT        = 120  # re-scan run folders every 2 min to catch PollingObserver misses
_DIR_STABILITY_POLL_DEFAULT       = 60   # full walk of running runs — heavier than the 10s checks


def watch_sequencer(sequencer, observer, watched_uuids: set, stability_tracker: dict):
    """
    Start watching a single sequencer location.
    Scans existing run folders, schedules the filesystem handler,
    and records the sequencer UUID so we don't watch it twice.
    """
    if not os.path.isdir(sequencer.location):
        logger.warning(f"location '{sequencer.location}' does not exist — skipping {sequencer.name}")
        return

    logger.info(f"scanning existing runs in: {sequencer.location}")
    scan_existing_runs(sequencer)

    handler = RunEventHandler(sequencer, stability_tracker)
    # recursive=False: only watch the top-level directory for new run folders.
    # Scanning run folder contents recursively on large SMB mounts is very slow
    # (each poll could take many minutes), causing missed detections.
    # Completion signal detection is handled by check_signal_files() in the main loop.
    observer.schedule(handler, path=sequencer.location, recursive=False)
    watched_uuids.add(str(sequencer.uuid))
    logger.info(f"watching: {sequencer.location} ({sequencer.name})")


def start():
    # wait for DB to be ready — retry loop handles Docker startup race
    sequencers = load_sequencers()

    observer = Observer(timeout=5)  # poll filesystem every 10 seconds
    observer.start()

    # track which sequencers are already being watched
    watched_uuids = set()

    # in-memory state for file_stability completion tracking
    # lost on watcher restart — tracker simply restarts fresh, worst case: one extra threshold wait
    stability_tracker = {}

    for sequencer in sequencers:
        watch_sequencer(sequencer, observer, watched_uuids, stability_tracker)

    if not watched_uuids:
        logger.warning("no sequencers found with a location — will keep checking every 60s")

    logger.info("started. press Ctrl+C to stop.")

    current_sequencers  = sequencers
    seq_elapsed         = 0
    stability_elapsed   = 0
    run_scan_elapsed    = 0
    dir_stability_elapsed = 0
    _STABILITY_POLL_INTERVAL = 10  # check stability every 10s (independent of sequencer poll)

    try:
        while True:
            time.sleep(1)
            seq_elapsed       += 1
            stability_elapsed += 1
            run_scan_elapsed  += 1
            dir_stability_elapsed += 1

            # ── stability + signal check (every 10s) ──────────────────────────
            if stability_elapsed >= _STABILITY_POLL_INTERVAL:
                stability_elapsed = 0
                check_file_stability(current_sequencers, stability_tracker)
                check_signal_files(current_sequencers)

            # ── directory stability (every 60s by default) ────────────────────
            if dir_stability_elapsed >= get_setting_int("dir_stability_poll_interval", _DIR_STABILITY_POLL_DEFAULT):
                dir_stability_elapsed = 0
                check_directory_stability(current_sequencers)

            # ── periodic run scan (every 2 min) — catch folders missed by PollingObserver ──
            # The PollingObserver can miss on_created when a folder is renamed on an SMB/NFS
            # mount (atomic rename = delete+create that the poller sometimes only sees half of).
            # scan_existing_runs only adds folders not already in the DB, so it is safe to call repeatedly.
            if run_scan_elapsed >= get_setting_int("run_scan_interval", _RUN_SCAN_INTERVAL_DEFAULT):
                run_scan_elapsed = 0
                for sequencer in current_sequencers:
                    if str(sequencer.uuid) in watched_uuids:
                        scan_existing_runs(sequencer)

            # ── sequencer poll (every 60s) — detect newly added sequencers ────
            if seq_elapsed >= get_setting_int("sequencer_check_interval", _SEQUENCER_CHECK_INTERVAL_DEFAULT):
                seq_elapsed = 0
                current_sequencers = query_sequencers()
                for sequencer in current_sequencers:
                    if str(sequencer.uuid) not in watched_uuids:
                        logger.info(f"new sequencer detected: {sequencer.name} — starting watch")
                        watch_sequencer(sequencer, observer, watched_uuids, stability_tracker)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start()
