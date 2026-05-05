import os
import sys
import time

from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

# allow imports from the backend folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.base  # registers all models so SQLAlchemy can resolve all relationships
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
            (signal_match == "prefix" and filename.startswith(signal))
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
                # even if already in DB, queue zip creation if completed and zip missing
                if existing.status == "completed":
                    zip_path = os.path.join(location, run_name, f"{run_name}.zip")
                    if os.path.exists(zip_path):
                        logger.info(f"zip already exists, skipping: {zip_path}")
                    else:
                        logger.info(f"queuing zip for existing run: {run_name}")
                        publish("run_completed", run_name, sequencer.uuid)
                continue

            # infer status from whether the completion signal file exists
            run_folder  = os.path.join(location, run_name)
            completed   = is_completed(run_folder, sequencer)
            status      = "completed" if completed else "running"

            db.add(Runs(name=run_name, sequencer_uuid=sequencer.uuid, status=status))
            added += 1
            logger.info(f"backfill → {run_name} (status={status})")

            # if completed, queue zip creation via RabbitMQ — never zip directly here
            # BAM files can be huge; the worker handles this as a background task
            if completed:
                zip_path = os.path.join(run_folder, f"{run_name}.zip")
                if os.path.exists(zip_path):
                    logger.info(f"zip already exists, skipping: {zip_path}")
                else:
                    logger.info(f"queuing zip for new run: {run_name}")
                    publish("run_completed", run_name, sequencer.uuid)

        db.commit()
        logger.info(f"scan done for '{sequencer.name}': {added} added, {skipped} skipped")

    finally:
        db.close()


def start():
    sequencers = load_sequencers()

    if not sequencers:
        print("[watcher] no sequencers found with a location. exiting.")
        return

    observer = Observer(timeout=10)  # poll every 10 seconds

    for sequencer in sequencers:
        if not os.path.isdir(sequencer.location):
            logger.warning(f"location '{sequencer.location}' does not exist — skipping {sequencer.name}")
            continue

        # scan existing folders before starting live watch
        logger.info(f"scanning existing runs in: {sequencer.location}")
        scan_existing_runs(sequencer)

        handler = RunEventHandler(sequencer)

        # recursive=True means we also get events from subfolders
        # (needed to detect files inside run folders)
        observer.schedule(handler, path=sequencer.location, recursive=True)
        logger.info(f"watching: {sequencer.location} ({sequencer.name})")

    observer.start()
    logger.info("started. press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start()
