"""Sample data for the static GUI demo (see build.py).

Shapes follow the backend API (backend/schemas/*, backend/api/v1/*); texts in
history details and logs follow what the backend actually writes. All timestamps
are generated relative to the build time so the dashboard charts look current.
"""
import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
VERSION = (REPO / "VERSION").read_text().strip()


def _uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"omicz-demo/{name}"))


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# ── Instrument models ─────────────────────────────────────────────────────────
TYPES = [
    {"id": 1, "uuid": _uuid("type/novaseq"), "name": "Illumina NovaSeq X",
     "completion_method": "signal", "completion_signal": "RTAComplete.txt", "signal_match": "exact",
     "stability_files": None, "stability_threshold_minutes": None,
     "dir_stability_minutes": None, "run_stability_minutes": None},
    {"id": 2, "uuid": _uuid("type/nextseq"), "name": "Illumina NextSeq 2000",
     "completion_method": "signal", "completion_signal": "CopyComplete.txt", "signal_match": "exact",
     "stability_files": None, "stability_threshold_minutes": None,
     "dir_stability_minutes": None, "run_stability_minutes": None},
    {"id": 3, "uuid": _uuid("type/promethion"), "name": "Oxford Nanopore PromethION",
     "completion_method": "directory_stability", "completion_signal": None, "signal_match": "exact",
     "stability_files": None, "stability_threshold_minutes": None,
     "dir_stability_minutes": 10, "run_stability_minutes": 60},
    {"id": 4, "uuid": _uuid("type/orbitrap"), "name": "Thermo Orbitrap Exploris 480",
     "completion_method": "file_stability", "completion_signal": None, "signal_match": "exact",
     "stability_files": ["sequence_report.csv"], "stability_threshold_minutes": 10,
     "dir_stability_minutes": None, "run_stability_minutes": None},
]
T = {t["name"]: t for t in TYPES}

# ── Instruments ───────────────────────────────────────────────────────────────
def _seq(i, name, type_name, status, mode, exclusions, created_days):
    created = _ago(days=created_days)
    return {"id": i, "uuid": _uuid(f"seq/{name}"), "name": name, "slug": name.lower(),
            "location": f"/runs/{name.lower()}", "author_id": None,
            "type_uuid": T[type_name]["uuid"], "status": status, "sent_to_tre": mode,
            "exclusions": exclusions, "created_at": _iso(created), "updated_at": _iso(created)}


SEQUENCERS = [
    _seq(1, "NovaSeq-X-01", "Illumina NovaSeq X", "active", "auto", ["Thumbnail_Images", "*.png"], 120),
    _seq(2, "NextSeq-2000-01", "Illumina NextSeq 2000", "active", "auto", ["Thumbnail_Images"], 110),
    _seq(3, "PromethION-24", "Oxford Nanopore PromethION", "active", "auto", ["*.tmp", "other_reports"], 60),
    _seq(4, "Orbitrap-Exploris-480", "Thermo Orbitrap Exploris 480", "active", "manual", ["*.tmp"], 30),
    _seq(5, "Orbitrap-Exploris-240", "Thermo Orbitrap Exploris 480", "inactive", "manual", [], 25),
]
S = {s["name"]: s for s in SEQUENCERS}

MOUNT_STATUS = {
    "mounts": [{"uuid": s["uuid"], "name": s["name"], "location": s["location"], "accessible": True}
               for s in SEQUENCERS if s["status"] == "active"],
    "all_accessible": True, "inaccessible_count": 0,
}

# ── Runs ──────────────────────────────────────────────────────────────────────
RUNS, HISTORY, DIRECTORIES = [], {}, {}

_PIPELINE = ["running", "running_finished", "queued", "checksumming", "queued", "moving", "verifying", "completed"]


def _run(name, seq, final, start, acq_hours, steps=None, progress=None, final_detail=None):
    """Add a run whose history follows the real pipeline up to `final`.

    steps: minutes spent in each pipeline state after acquisition (checksum, queue, upload, verify)."""
    rid = len(RUNS) + 1
    run_uuid = _uuid(f"run/{rid}")
    s = S[seq]
    hist, t = [], start
    hist.append(("running", None, t))
    if final not in ("running", "transfer_conflict"):
        t = t + timedelta(hours=acq_hours)
        hist.append(("running_finished", None, t))
    path = {"running": 1, "running_finished": 2, "queued": 3, "checksumming": 4,
            "moving": 6, "verifying": 7, "completed": 8,
            "move_failed": 6, "verify_failed": 7, "transfer_conflict": 1, "failed": 4}[final]
    mins = iter(steps or [1, 18, 1, 95, 6])
    for st in _PIPELINE[2:path]:
        t = t + timedelta(minutes=next(mins, 2))
        hist.append((st, None, t))
    if final in ("move_failed", "verify_failed", "transfer_conflict", "failed"):
        t = t + timedelta(minutes=next(mins, 5))
        hist.append((final, final_detail, t))
    elif final_detail:
        hist[-1] = (hist[-1][0], final_detail, hist[-1][2])
    HISTORY[run_uuid] = [{"uuid": _uuid(f"hist/{rid}/{i}"), "status": st, "detail": d, "created_at": _iso(ts)}
                         for i, (st, d, ts) in enumerate(hist)]
    RUNS.append({"id": rid, "uuid": run_uuid, "name": name, "sequencer_uuid": s["uuid"],
                 "sequencer_name": s["name"], "sequencer_sent_to_tre": s["sent_to_tre"],
                 "status": final, "progress": progress,
                 "created_at": _iso(start), "updated_at": _iso(hist[-1][2])})
    DIRECTORIES[run_uuid] = []
    return run_uuid


def _ilmn(day_offset, inst, num, fc):
    d = (NOW - timedelta(days=day_offset)).strftime("%y%m%d")
    return f"{d}_{inst}_{num:04d}_{fc}"


def _ont(day_offset, hhmm, pos, flow, h):
    d = NOW - timedelta(days=day_offset)
    return f"{d.strftime('%Y%m%d')}_{hhmm}_{pos}_{flow}_{h}"


def _ms(day_offset, sample):
    return f"{(NOW - timedelta(days=day_offset)).strftime('%Y-%m-%d')}_{sample}"


# Completed history over the last two weeks
_run(_ilmn(13, "LH00419", 211, "A22KJ3LT3"), "NovaSeq-X-01", "completed", _ago(days=13, hours=2), 26)
_run(_ilmn(12, "VH01237", 87, "AAFGJ7KM5"), "NextSeq-2000-01", "completed", _ago(days=12, hours=5), 19, [1, 4, 1, 22, 3])
_run(_ilmn(10, "VH01237", 88, "AAFGJ8CM5"), "NextSeq-2000-01", "completed", _ago(days=10, hours=8), 21, [1, 5, 1, 25, 4])
_run(_ont(9, "1532", "P2S-01234-A", "PAW41327", "8c1f2d3e"), "PromethION-24", "completed", _ago(days=9, hours=3), 72, [1, 2, 1, 14, 9])
_run(_ms(8, "HeLa_QC_01"), "Orbitrap-Exploris-480", "completed", _ago(days=8, hours=4), 2, [1, 1, 1, 2, 2])
_run(_ilmn(7, "LH00419", 212, "A22KJ7LT3"), "NovaSeq-X-01", "completed", _ago(days=7, hours=1), 25, [1, 31, 1, 142, 11])
_run(_ms(6, "Plasma_cohort_B12"), "Orbitrap-Exploris-480", "completed", _ago(days=6, hours=6), 3, [1, 1, 1, 3, 2])
_run(_ilmn(5, "VH01237", 89, "AAFGK2CM5"), "NextSeq-2000-01", "verify_failed", _ago(days=5, hours=2), 20, [1, 4, 1, 24, 6],
     final_detail="File failed verification: Data/Intensities/BaseCalls/L001/C153.1/s_1_2103.cbcl "
                  "(sha256: 4be1c0a9d7e5f2a1b8c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9)")
_run(_ms(4, "Plasma_cohort_B13"), "Orbitrap-Exploris-480", "completed", _ago(days=4, hours=7), 3, [1, 1, 1, 3, 2])
_run(_ilmn(4, "VH01237", 90, "AAFGK3CM5"), "NextSeq-2000-01", "completed", _ago(days=4, hours=1), 20, [1, 5, 1, 23, 4])
_run(_ilmn(3, "LH00419", 213, "A22KL1LT3"), "NovaSeq-X-01", "move_failed", _ago(days=3, hours=4), 24, [1, 29, 1, 64],
     final_detail="An error occurred (BadRequest) when calling the UploadPart operation: Bad Request")
conflict = _run(_ont(3, "0914", "P2S-01234-B", "PAW41419", "1b7e9a0c"), "PromethION-24", "transfer_conflict", _ago(days=3, hours=8), 0, [400],
                final_detail="Directory 'pod5' changed after it was sent to the TRE.\n"
                             "Modified (1): pod5/PAW41419_1b7e9a0c_0.pod5\n"
                             "Uploaded objects cannot be overwritten. Check the instrument output and contact the TRE administrator.")
_run(_ms(2, "Plasma_cohort_B14"), "Orbitrap-Exploris-480", "completed", _ago(days=2, hours=5), 3, [1, 1, 1, 3, 2])
_run(_ilmn(2, "VH01237", 91, "AAFGK5CM5"), "NextSeq-2000-01", "completed", _ago(days=2, hours=9), 19, [1, 4, 1, 21, 3])

# Runs in the pipeline right now
_run(_ilmn(1, "LH00419", 214, "A22KM4LT3"), "NovaSeq-X-01", "verifying", _ago(days=1, hours=8), 25, [1, 33, 1, 158])
_run(_ilmn(1, "VH01237", 92, "AAFGK7CM5"), "NextSeq-2000-01", "moving", _ago(days=1, hours=2), 22, [1, 6, 1],
     progress="38.2 GB / 112.7 GB")
_run(_ms(0, "Plasma_cohort_B15"), "Orbitrap-Exploris-480", "running_finished", _ago(hours=5), 3)
_run(_ms(0, "HeLa_QC_02"), "Orbitrap-Exploris-480", "running", _ago(minutes=50), 0)
ont_live = _run(_ont(0, "0347", "P2S-01234-A", "PAW41502", "5d2c8b71"), "PromethION-24", "running", _ago(hours=9), 0)
_run(_ilmn(0, "LH00419", 215, "A22KN2LT3"), "NovaSeq-X-01", "running", _ago(hours=14), 0)

# Two runs waiting in the queue behind the active upload
for name, seq, hrs in ((_ilmn(1, "VH01237", 93, "AAFGK8CM5"), "NextSeq-2000-01", 20),
                       (_ilmn(1, "LH00419", 216, "A22KN5LT3"), "NovaSeq-X-01", 27)):
    _run(name, seq, "queued", _ago(hours=hrs), hrs - 1, [1, 2])

# Directory stability state for the PromethION runs
DIRECTORIES[ont_live] = [
    {"uuid": _uuid("dir/live/fastq_fail"), "name": "fastq_fail", "state": "sent", "file_count": 212,
     "total_bytes": 3_812_000_000, "stable_since": _iso(_ago(hours=2, minutes=40)),
     "sent_at": _iso(_ago(hours=2, minutes=29)), "progress": None, "detail": None},
    {"uuid": _uuid("dir/live/fastq_pass"), "name": "fastq_pass", "state": "uploading", "file_count": 1388,
     "total_bytes": 41_200_000_000, "stable_since": _iso(_ago(minutes=24)), "sent_at": None,
     "progress": "512 / 1388 files · 15.4 GB / 38.4 GB", "detail": None},
    {"uuid": _uuid("dir/live/pod5"), "name": "pod5", "state": "waiting", "file_count": 1840,
     "total_bytes": 402_000_000_000, "stable_since": None, "sent_at": None, "progress": None, "detail": None},
    {"uuid": _uuid("dir/live/sequencing_summary"), "name": "sequencing_summary", "state": "queued", "file_count": 1,
     "total_bytes": 1_900_000_000, "stable_since": _iso(_ago(minutes=12)), "sent_at": None, "progress": None, "detail": None},
]
DIRECTORIES[conflict] = [
    {"uuid": _uuid("dir/conf/fastq_pass"), "name": "fastq_pass", "state": "sent", "file_count": 1650,
     "total_bytes": 45_700_000_000, "stable_since": _iso(_ago(days=3, hours=3, minutes=10)),
     "sent_at": _iso(_ago(days=3, hours=3)), "progress": None, "detail": None},
    {"uuid": _uuid("dir/conf/pod5"), "name": "pod5", "state": "conflict", "file_count": 2010,
     "total_bytes": 438_000_000_000, "stable_since": _iso(_ago(days=3, hours=2, minutes=40)),
     "sent_at": _iso(_ago(days=3, hours=1, minutes=50)), "progress": None,
     "detail": HISTORY[conflict][-1]["detail"]},
]

RUNS.sort(key=lambda r: r["created_at"], reverse=True)
R = {r["uuid"]: r for r in RUNS}
QUEUE_STATES = ("queued", "checksumming", "moving", "verifying")
FAILED_STATES = ("move_failed", "verify_failed", "failed")


def runs_page(params: dict) -> dict:
    statuses = params.get("status")
    if isinstance(statuses, str):
        statuses = [statuses]
    rows = [r for r in RUNS if not statuses or r["status"] in statuses]
    if params.get("sequencer_uuid"):
        rows = [r for r in rows if r["sequencer_uuid"] == params["sequencer_uuid"]]
    if params.get("search"):
        rows = [r for r in rows if params["search"].lower() in r["name"].lower()]
    if params.get("order") == "asc":
        rows = rows[::-1]
    skip, limit = int(params.get("skip", 0)), int(params.get("limit", 50))
    return {"total": len(rows), "skip": skip, "limit": limit, "results": rows[skip:skip + limit]}


def queue_page() -> dict:
    order = {"moving": 0, "checksumming": 0, "verifying": 1, "queued": 2}
    rows = sorted((r for r in RUNS if r["status"] in QUEUE_STATES), key=lambda r: order[r["status"]])
    return {"total": len(rows), "skip": 0, "limit": 50, "results": rows}


# ── Settings (the real defaults, read from the backend source) ────────────────
def _settings() -> list:
    src = (REPO / "backend/db/repositories/settings.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DEFAULTS" for t in node.targets):
            rows = ast.literal_eval(node.value)
            for r in rows:
                r["updated_at"] = None
                if r["key"] == "pagination_page_size":
                    r["value"] = "50"   # one page per list in the static demo
            return rows
    return []


SETTINGS = _settings()

# ── Containers ────────────────────────────────────────────────────────────────
CONTAINERS = [
    {"id": f"{i:x}a3c9e1f07b"[:10], "name": f"fastapi_gateway_{n}", "status": "running", "image": img}
    for i, (n, img) in enumerate([
        ("adminer", "adminer:latest"), ("backend", "omicz-gateway-component-backend:latest"),
        ("backup", "omicz-gateway-component-backup:latest"), ("db", "postgres:15"),
        ("frontend", "omicz-gateway-component-frontend:latest"), ("rabbitmq", "rabbitmq:3-management"),
        ("watcher", "omicz-gateway-component-watcher:latest"), ("worker", "omicz-gateway-component-worker:latest"),
    ], start=1)
]

# ── Logs ──────────────────────────────────────────────────────────────────────
def _log(minutes_ago, level, where, msg):
    ts = (NOW - timedelta(minutes=minutes_ago)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return f"{ts} | {level:<8} | {where} | {msg}"


_moving = next(r for r in RUNS if r["status"] == "moving")
_verifying = next(r for r in RUNS if r["status"] == "verifying")
_live_ont = R[ont_live]

LOGS = {
    "backend": [
        _log(240, "INFO", "backend:41", "application startup complete"),
        _log(180, "INFO", "backend.runs:153", f"start-upload requested for run '{_moving['name']}'"),
        _log(95, "INFO", "backend.settings:28", "setting 'upload_engine' = 'boto3'"),
        _log(12, "INFO", "backend.runs:121", f"verify-check for '{_verifying['name']}': pending"),
        _log(3, "DEBUG", "backend.sequencers:22", "mount-status: 4 of 4 locations accessible"),
    ],
    "watcher": [
        _log(600, "INFO", "watcher:88", "watching 4 active instruments (polling observer)"),
        _log(540, "INFO", "watcher:142", f"new run folder registered: {_live_ont['name']} (PromethION-24)"),
        _log(160, "INFO", "dir_stability:201", f"'{_live_ont['name']}': folder 'fastq_fail' quiet for 10 min — queued for upload"),
        _log(50, "INFO", "watcher:142", "new run folder registered: " + next(r['name'] for r in RUNS if r['status'] == 'running' and 'HeLa' in r['name'])),
        _log(24, "INFO", "dir_stability:201", f"'{_live_ont['name']}': folder 'fastq_pass' quiet for 10 min — queued for upload"),
        _log(12, "INFO", "dir_stability:201", f"'{_live_ont['name']}': folder 'sequencing_summary' quiet for 10 min — queued for upload"),
        _log(1, "DEBUG", "watcher:210", "rescan: no unregistered folders"),
    ],
    "worker": [
        _log(260, "INFO", "checksum:137", "checksumming 4180 files (112.7 GB) using 4 threads"),
        _log(250, "INFO", "worker:540", f"[upload] '{_moving['name']}': 4180 files, engine boto3, part size 16 MiB"),
        _log(120, "WARNING", "worker:311", "[upload] UploadPart rejected (HTTP 400, no error code) — retrying part 1873 of 2410 (attempt 2/5)"),
        _log(119, "INFO", "worker:318", "[upload] part 1873 accepted on attempt 2"),
        _log(24, "INFO", "worker:173", f"[dir-upload] '{_live_ont['name']}/fastq_pass': 1388 files"),
        _log(2, "DEBUG", "worker:633", f"[verifier] '{_verifying['name']}' pending (1140s / 7980s)"),
    ],
    "backup": [
        _log(2880, "INFO", "backup:61", "pg_dump written: gateway_backup_2.sql.gz (14.2 MB)"),
        _log(2880, "INFO", "backup:74", "retention: keeping 10 most recent backups"),
    ],
    "frontend": [
        _log(30, "INFO", "frontend:20", "GET / 200"),
        _log(5, "INFO", "frontend:20", "GET /acquisition-runs/ 200"),
    ],
}

SYSTEM_VERSION = {"current": VERSION, "latest": VERSION, "update_available": False, "workspace_mounted": True}
