from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

CHANGELOG = [
    {
        "version": "1.1.0",
        "date": "2026-08-05",
        "tag": "Latest",
        "tag_color": "indigo",
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
        "tag": None,
        "tag_color": None,
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
        "tag": None,
        "tag_color": None,
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
        "tag": None,
        "tag_color": None,
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
        "tag": None,
        "tag_color": None,
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
        "tag": None,
        "tag_color": None,
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
