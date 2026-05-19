import os
import sys
import time

from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

# allow imports from the backend folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # registers all models so SQLAlchemy can resolve relationships
from db.session import SESSION_LOCAL
from db.models.sequencers import Sequencers
from db.models.runs import Runs
from services.publisher import publish
from core.logger import get_logger

logger = get_logger("watcher")


class RunEventHandler(FileSystemEventHandler):
    """
    Handles filesystem events for a single sequencer location.

    Directory structure we're watching:
        sequencer.location/                  ← we watch this
            run_2026_04_15/                  ← depth 1: new run folder
                **_complete.txt              ← depth 2: completion signal
    """

    def __init__(self, sequencer):
        self.sequencer = sequencer
        self.location  = sequencer.location

        # store the completion signal info from the sequencer type
        # so we don't need to re-query DB on every event
        if sequencer.type:
            self.signal       = sequencer.type.completion_signal
            self.signal_match = sequencer.type.signal_match
        else:
            self.signal       = None
            self.signal_match = None

    def on_created(self, event):
        # get the path relative to the sequencer location
        # e.g. "run_2026_04_15" or "run_2026_04_15/RTAComplete.txt"
        relative = os.path.relpath(event.src_path, self.location)
        parts    = relative.split(os.sep)

        # ── depth 1: a new folder directly inside the location ────────────────
        # parts = ["run_2026_04_15"]
        if len(parts) == 1 and event.is_directory:
            run_name = parts[0]
            logger.info(f"new run detected: {run_name} on sequencer {self.sequencer.name}")
            publish("run_created", run_name, self.sequencer.uuid)

        # ── depth 2: a new file inside a run folder ────────────────────────────
        # parts = ["run_2026_04_15", "RTAComplete.txt"]
        elif len(parts) == 2 and not event.is_directory:
            run_name = parts[0]
            filename = parts[1]

            if self.signal is None:
                # sequencer has no type set — we don't know what to look for
                logger.warning(f"sequencer '{self.sequencer.name}' has no type set — skipping completion check")
                return

            # check if this file matches the completion signal
            matched = (
                (self.signal_match == "exact"  and filename == self.signal) or
                (self.signal_match == "prefix" and filename.startswith(self.signal)) or
                (self.signal_match == "suffix" and filename.endswith(self.signal))
            )

            if matched:
                logger.info(f"run completed: {run_name} on sequencer {self.sequencer.name}")
                publish("run_completed", run_name, self.sequencer.uuid)


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
    """
    if not sequencer.type:
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
                skipped += 1
                continue

            # infer status from whether the completion signal file exists
            run_folder  = os.path.join(location, run_name)
            completed   = is_completed(run_folder, sequencer)
            status      = "running_finished" if completed else "running"

            db.add(Runs(name=run_name, sequencer_uuid=sequencer.uuid, status=status))
            added += 1
            logger.info(f"backfill → {run_name} (status={status})")

            # if completed, queue upload via RabbitMQ — the worker handles S3 upload
            if completed:
                publish("run_completed", run_name, sequencer.uuid)

        db.commit()
        logger.info(f"scan done for '{sequencer.name}': {added} added, {skipped} skipped")

    finally:
        db.close()


SEQUENCER_CHECK_INTERVAL = 60  # seconds between DB polls for new sequencers


def watch_sequencer(sequencer, observer, watched_uuids: set):
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

    handler = RunEventHandler(sequencer)
    observer.schedule(handler, path=sequencer.location, recursive=True)
    watched_uuids.add(str(sequencer.uuid))
    logger.info(f"watching: {sequencer.location} ({sequencer.name})")


def start():
    # wait for DB to be ready — retry loop handles Docker startup race
    sequencers = load_sequencers()

    observer = Observer(timeout=5)  # poll filesystem every 10 seconds
    observer.start()

    # track which sequencers are already being watched
    watched_uuids = set()

    for sequencer in sequencers:
        watch_sequencer(sequencer, observer, watched_uuids)

    if not watched_uuids:
        logger.warning("no sequencers found with a location — will keep checking every 60s")

    logger.info("started. press Ctrl+C to stop.")

    elapsed = 0
    try:
        while True:
            time.sleep(1)
            elapsed += 1

            if elapsed >= SEQUENCER_CHECK_INTERVAL:
                elapsed = 0
                # re-query DB for sequencers added since startup
                for sequencer in query_sequencers():
                    if str(sequencer.uuid) not in watched_uuids:
                        logger.info(f"new sequencer detected: {sequencer.name} — starting watch")
                        watch_sequencer(sequencer, observer, watched_uuids)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start()
