from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

CHANGELOG = [
    {
        "version": "1.0.0",
        "date": "2026-07-27",
        "tag": "Latest",
        "tag_color": "indigo",
        "sections": {
            "New Features": [
                "Dashboard with live stat widgets: Sequencing, Ready to Upload, Pipeline, Failed, Completed, Sequencers",
                "Chart.js charts on dashboard: run status donut, 14-day activity bar chart, per-sequencer horizontal bar",
                "Graphical SVG countdown ring on all auto-refresh pages — Logs, Containers, Queue, Run Detail (click to refresh immediately)",
                "Sequencer active/inactive toggle button directly on the sequencer list — no need to open the detail page",
                "Settings and Logs pages added to the navigation and sidebar",
                "Containers page shows Docker service status with restart action",
                "Version badge in sidebar links to this changelog page",
            ],
            "Pipeline Improvements": [
                "Two-queue RabbitMQ architecture: run events (run_created, run_completed) on a separate fast queue so new runs are always detected even during long uploads",
                "Periodic run scan every 2 minutes as a safety net for runs missed by the filesystem watcher (e.g. renamed folders on SMB/NFS)",
                "S3 single-file PUT upload with live byte-level progress reporting",
                "kubectl proxy auto-restart managed by the gateway instead of manual port-forward",
            ],
            "Bug Fixes": [
                "Fixed stale .CHECKSUM file being reused after run folder contents changed, causing TRE validation failure",
                "Fixed user upload retries being blocked by the stale_queued guard when checksum_file was still set in DB",
                "Fixed new runs not detected while a long upload was in progress (single-queue blocking issue)",
                "Fixed PollingObserver missing run folders renamed on SMB/NFS (untitled → final name race condition)",
                "Fixed dashboard showing 0/0 sequencers due to limit=100 exceeding PAGINATION_MAX_LIMIT=50",
                "Fixed chart data HTML-escaped by Jinja2 auto-escaping (switched from json.dumps to tojson filter)",
                "Fixed verify_failed guard firing prematurely during race between upload event and DB write",
            ],
        },
    },
]


@router.get("/")
def changelog(request: Request):
    return templates.TemplateResponse(request, "changelog.html", {"changelog": CHANGELOG})
