from fastapi import APIRouter, Request

router = APIRouter()
from shared_templates import templates

CHANGELOG = [
    {
        "version": "1.2.1",
        "date": "2026-09-30",
        "sections": {
            "Bug Fixes": [
                "Fixed Settings → Update failing at sites that had edited docker-compose.yml (e.g. to add an instrument) — local edits are now set aside during the update and put back afterwards; if they overlap with the new version, the update is rolled back cleanly and the site stays on its current version with its changes intact",
                "The database update (alembic upgrade head) now always runs during Update instead of only when migration files were detected in git's output",
                "A failed database update is now reported as a warning, and the worker and watcher keep running the previous version instead of being restarted on code that needs the new schema",
                "Reverted the DB_HOST_PORT change to docker-compose.yml from 1.2.0 so sites on 1.1.x with an edited docker-compose.yml can update with their current Update button; set a different host port in docker-compose.override.yml instead",
            ],
            "Improvements": [
                "Update asks for confirmation when transfers are running, because restarting the worker interrupts them",
                "Update does nothing and restarts nothing when the site is already up to date, and reports when docker-compose.yml, a Dockerfile or requirements.txt changed and a manual 'docker compose up -d --build' is needed",
                "The latest-version check is cached for 15 minutes (it ran on every page load and could hit GitHub's rate limit); the Check button on the Settings page always asks GitHub directly",
                "Site-specific settings such as additional instrument folders go into the git-ignored docker-compose.override.yml (see docker-compose.override.example.yml and the README), so updates never conflict with them",
            ],
        },
    },
    {
        "version": "1.2.0",
        "date": "2026-09-29",
        "sections": {
            "New Features": [
                "Directory stability completion method: each top-level folder of a run is sent to the TRE as soon as it has not changed for a set time, and the run is finalized once the whole run folder is quiet — checksums of folders already sent are reused",
                "New Transfer Conflict status: a folder that changes after it was sent (file modified or deleted) puts the run on hold and lists the changed files, since uploaded files cannot be overwritten in the TRE",
                "Directories panel on the run detail page with the state of every folder and a Retry button for failed folder uploads",
                "Interrupted transfers resume: every file's checksum and upload is recorded, so Retry sends only the files that are missing and does not re-hash unchanged data",
                "Dark mode, following the system setting by default, with a toggle in the sidebar",
            ],
            "Improvements": [
                "TRE verification runs outside the transfer queue — the next run uploads while earlier runs wait for TRE confirmation (a burst of 5 runs finished in about 2 minutes instead of about 20)",
                "TRE confirmation wait raised from 10 minutes to 1 hour, plus extra time for large runs (setting verify_minutes_per_100gb, default 24: 1 TB → 5 hours)",
                "Runs waiting for TRE confirmation are resumed after a worker restart instead of being marked as failed",
                "Upload progress is written to the database at most every 2 seconds instead of several times per MB",
                "Database host port is configurable (DB_HOST_PORT, default 5432)",
            ],
            "Bug Fixes": [
                "Fixed finished runs found at installation (backfill) never being transferred — they stayed at Acquisition Complete until the worker restarted",
                "Fixed the worker losing its RabbitMQ connection during uploads or verifications longer than about 3 minutes (missed heartbeats), which restarted the worker and processed the task twice",
                "Fixed runs being shown as Transfer Validation while only waiting in the queue after Retry Verification",
            ],
        },
    },
    {
        "version": "1.1.17",
        "date": "2026-08-10",
        "sections": {
            "Bug Fixes": [
                "Fixed Containers page showing a Docker connection error after docker compose rebuild — accessing the image of a container running on a deleted image now falls back gracefully instead of crashing the entire listing",
            ],
        },
    },
    {
        "version": "1.1.16",
        "date": "2026-08-07",
        "sections": {
            "New Features": [
                "Automatic database backups: a dedicated backup service periodically dumps and gzips the database into a backups/ folder, with the interval and how many backups to keep configurable from Settings",
            ],
        },
    },
    {
        "version": "1.1.15",
        "date": "2026-08-07",
        "sections": {
            "Bug Fixes": [
                "Fixed Alembic migration crash when seeding the checksum_chunk_size_mb setting (bound parameters were passed directly to op.execute(), which doesn't accept them)",
                "Fixed 500 error opening the New Instrument Type page, caused by missing UI language context",
                "Fixed unmatched routes and 404s returning raw JSON instead of a proper not-found page",
                "Removed an orphaned /test route referencing a nonexistent template",
                "Fixed the Logs viewer hiding service tabs (checksum, publisher, tre) that hadn't logged anything yet",
                "Fixed run, sequencer, and settings timestamps displaying in UTC instead of local time — including the live run-duration timer, which was silently off by the UTC offset",
                "Fixed the Changelog page showing a stale current-version badge and 'Latest' tag instead of the real running version",
            ],
            "Improvements": [
                "Changelog 'Latest' tag is now computed from the actual running version instead of hardcoded per entry",
                "Added a large 404 numeral to the not-found page so it reads clearly as a not-found page",
                "Updated default settings for fresh installs: checksum read chunk size 256 MB, 8 items per page, 60s upload retry wait cap",
            ],
        },
    },
    {
        "version": "1.1.7",
        "date": "2026-08-05",
        "sections": {
            "New Features": [
                "One-click in-app update: Settings page shows current and latest version, fetches from GitHub automatically, and updates all services with a single button click",
                "Update notification: animated red dot on the version badge and a banner on the Dashboard appear automatically when a new version is available",
                "Version check runs on every page load using server-side GitHub API caching (5-minute TTL) — no manual check needed",
                "Frontend container restarts automatically as part of the update flow so template changes take effect immediately",
            ],
            "Bug Fixes": [
                "Fixed auto-upload runs getting stuck in 'Sequencing Done' after worker restart — worker now re-queues them automatically on startup",
                "Fixed 'Send to TRE' button appearing for auto-upload sequencers when the run is already queued — replaced with a clear 'Auto-upload queued — waiting for worker…' indicator",
                "Fixed run detail page stopping polling when status is 'Sequencing Done' for auto sequencers — page now refreshes automatically until the pipeline resumes",
                "Fixed Changelog missing from sidebar navigation",
            ],
        },
    },
    {
        "version": "1.1.0",
        "date": "2026-08-05",
        "sections": {
            "Bug Fixes": [
                "Fixed auto-upload runs getting stuck in 'Sequencing Done' after worker restart — worker now re-queues them automatically on startup",
                "Fixed 'Send to TRE' button appearing for auto-upload sequencers when the run is already queued — replaced with a clear 'Auto-upload queued — waiting for worker…' indicator",
                "Fixed run detail page stopping polling when status is 'Sequencing Done' for auto sequencers — page now refreshes automatically until the pipeline resumes",
            ],
        },
    },
    {
        "version": "1.0.0",
        "date": "2026-07-27",
        "sections": {
            "New Features": [
                "Dashboard with live stat widgets: Sequencing, Ready to Upload, Pipeline, Failed, Completed, Sequencers",
                "Chart.js charts on dashboard: run status donut, 14-day activity bar chart, per-sequencer horizontal bar",
                "Graphical SVG countdown ring on all auto-refresh pages — Logs, Containers, Queue, Run Detail (click to refresh immediately)",
                "Sequencer active/inactive toggle button directly on the sequencer list — no need to open the detail page",
                "Version badge in sidebar links to this changelog page",
                "Mount health monitoring: backend checks filesystem accessibility of every sequencer location at page load",
                "Warning banner on Dashboard and Sequencers page when storage mounts are inaccessible, with per-card badge on affected sequencers",
                "One-click Restart Watcher button in the warning banner — watcher picks up newly-mounted locations within its 60 s poll cycle",
            ],
            "Pipeline Improvements": [
                "Two-queue RabbitMQ architecture: run events (run_created, run_completed) on a separate fast queue so new runs are always detected even during long uploads",
                "Periodic run scan every 2 minutes as a safety net for runs missed by the filesystem watcher (e.g. renamed folders on SMB/NFS)",
            ],
            "Bug Fixes": [
                "Fixed stale .CHECKSUM file being reused after run folder contents changed, causing TRE validation failure",
                "Fixed user upload retries being blocked by the stale_queued guard when checksum_file was still set in DB",
                "Fixed new runs not detected while a long upload was in progress (single-queue blocking issue)",
                "Fixed PollingObserver missing run folders renamed on SMB/NFS (untitled → final name race condition)",
                "Fixed dashboard showing 0/0 sequencers due to limit=100 exceeding PAGINATION_MAX_LIMIT=50",
                "Fixed verify_failed guard firing prematurely during race between upload event and DB write",
            ],
        },
    },
    {
        "version": "0.9.0",
        "date": "2026-07-24",
        "sections": {
            "New Features": [
                "Settings page: all pipeline and UI timings configurable from the browser (pagination size, refresh intervals, log line count, run scan interval)",
                "Logs page: live log viewer for all services (backend, worker, watcher, frontend) with syntax-coloured output, auto-scroll, and download",
                "Containers page: Docker container status overview with one-click restart per service",
                "Direct S3 HTTPS upload — removed dependency on kubectl proxy for data transfer",
            ],
            "Improvements": [
                "Single-file PUT upload replaces multipart approach, reducing overhead for large run folders",
                "Live byte-level upload progress reported to the run detail page during transfer",
                "kubectl proxy auto-restart managed internally so port-forwarding no longer requires manual intervention",
                "Upload event race condition fixed: verify_failed guard now waits for DB write to settle before evaluating",
            ],
        },
    },
    {
        "version": "0.8.0",
        "date": "2026-07-23",
        "sections": {
            "New Features": [
                "Exclusions field on sequencer: list of folder/file patterns to skip during checksumming and upload",
                "File stability completion method: watcher waits for run folder to stop changing before marking sequencing done",
                "Checksum filename stored in DB so verification always targets the correct S3 object",
                "S3 checksum bucket verification: TRE confirmation pulled directly from S3 instead of polling an API",
                "Soft-delete for runs: removes the record from the list without touching any files; guarded for completed runs",
                "Delete button on run detail page with confirmation dialog",
            ],
            "Bug Fixes": [
                "Fixed duplicate run rows appearing in the database on rapid watcher events",
                "Fixed stale pipeline restart loop when a run was already in a terminal state",
                "Fixed pipeline stepper alignment when connector widths were inconsistent",
            ],
        },
    },
    {
        "version": "0.7.0",
        "date": "2026-07-21",
        "sections": {
            "New Features": [
                "Duplicate upload guard: detects a run already queued with a valid checksum and discards the redundant message",
                "Status history detail field: error messages and stack traces attached to failed history entries",
                "Retry / Re-check button on run detail page for failed states",
                "Move_failed error detail shown inline on the run detail page",
                "Delete guard: completed runs cannot be accidentally deleted",
            ],
            "Improvements": [
                "Filter pills on Runs list: Sequencing pill now shows only actively-sequencing runs (not running_finished)",
                "Failed filter pill removed — failed runs shown via the status filter dropdown instead",
                "Filter pill buttons fixed: use data-attributes instead of inline onclick to avoid XSS and state issues",
                "Watcher: set recursive=False and added signal-file checks to reduce false positives on SMB shares",
                "Timezone-aware logging across all services for consistent timestamps in Logs viewer",
            ],
            "Bug Fixes": [
                "Fixed duplicate status history entries being written on repeated pipeline restarts",
                "Fixed watcher not backfilling the database on startup when runs already existed on disk",
            ],
        },
    },
    {
        "version": "0.5.0",
        "date": "2026-05-19",
        "sections": {
            "New Features": [
                "Initial public release of OmiCZ GateWay",
                "Filesystem watcher: automatically detects new sequencing run folders on registered sequencer locations",
                "Run pipeline: checksum → S3 upload → TRE verification, orchestrated via RabbitMQ",
                "Run detail page: pipeline stepper, status history timeline, progress bar for active stages",
                "Runs list with pagination and status filtering",
                "Sequencer management: register, edit, activate/deactivate sequencer machines",
                "Sequencer type catalogue for grouping machines by platform (Illumina, ONT, Aviti)",
                "Upload queue view: active and waiting runs in one place",
                "Alembic database migrations tracked in version control",
                "Publisher logger and timezone-aware logging for all services",
            ],
        },
    },
]


@router.get("/")
def changelog(request: Request):
    return templates.TemplateResponse(request, "changelog.html", {"changelog": CHANGELOG})
