"""
Central UI terminology dictionary.
All user-visible labels are defined here.

Templates access entries via {{ lang.key }}.
JavaScript inside templates can use Jinja2 interpolation: '{{ lang.key }}'.

To rename a term, change its value here — every template updates automatically.
"""

LANG: dict[str, str] = {
    # ── Core entities ─────────────────────────────────────────────────────────
    "instrument":              "Instrument",
    "instruments":             "Instruments",
    "instrument_model":        "Instrument Model",
    "instrument_models":       "Instrument Models",
    "instrument_output_path":  "Instrument Output Path",

    "acquisition_run":         "Acquisition Run",
    "acquisition_runs":        "Acquisition Runs",
    "acquisition_data_folder": "Acquisition Data Folder",

    "transfer_queue":          "Transfer Queue",
    "transfer_workflow":       "Transfer Workflow",
    "transfer_to_tre":         "Transfer to TRE",
    "automatic_transfer":      "Automatic Transfer",

    # ── Sidebar nav (short labels) ────────────────────────────────────────────
    "nav_runs":                "Acquisition Runs",
    "nav_queue":               "Transfer Queue",
    "nav_instruments":         "Instruments",
    "nav_instrument_models":   "Inst. Models",

    # ── Run status labels ─────────────────────────────────────────────────────
    "status_running":          "Data Acquisition",
    "status_running_finished": "Acquisition Complete",
    "status_queued":           "Queued",
    "status_checksumming":     "Integrity Check",
    "status_moving":           "Data Transfer",
    "status_verifying":        "Transfer Validation",
    "status_completed":        "Transfer Complete",
    "status_move_failed":      "Data Transfer Failed",
    "status_verify_failed":    "Transfer Validation Failed",
    "status_failed":           "Failed",
    "status_transfer_conflict": "Transfer Conflict",

    # ── Pipeline stepper stage labels ─────────────────────────────────────────
    "stepper_sequencing":      "Data Acquisition",
    "stepper_checksumming":    "Integrity Check",
    "stepper_uploading":       "Data Transfer",
    "stepper_verifying":       "Transfer Validation",
    "stepper_completed":       "Transfer Complete",

    # ── Progress box status titles ────────────────────────────────────────────
    "progress_checksumming":   "Integrity check in progress",
    "progress_moving":         "Transferring to TRE",
    "progress_verifying":      "Waiting for TRE confirmation",

    # ── Settings labels ───────────────────────────────────────────────────────
    "setting_active_refresh":  "Transfer Status Refresh Interval",
    "setting_idle_refresh":    "Acquisition Status Refresh Interval",
    "setting_sequencer_check": "Instrument Registration Check Interval",
    "setting_run_detection":   "Acquisition Registration Delay",
}
