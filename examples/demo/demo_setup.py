"""One-shot setup for the local demo: creates the instrument models and instruments
for the example runs in examples/runs through the gateway's API. Safe to run again:
anything that already exists is left as it is. Standard library only.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API      = os.environ.get("BACKEND_URL", "http://backend:8000")
USER     = os.environ["ADMIN_USERNAME"]
PASSWORD = os.environ["ADMIN_PASSWORD"]

MODELS = [
    {"name": "Demo Illumina", "completion_method": "signal",
     "completion_signal": "RTAComplete.txt", "signal_match": "exact"},
    {"name": "Demo Nanopore", "completion_method": "signal",
     "completion_signal": "final_summary_", "signal_match": "prefix"},
    {"name": "Demo timsTOF", "completion_method": "file_stability",
     "stability_files": ["analysis.tdf"], "stability_threshold_minutes": 1},
]
INSTRUMENTS = [
    {"name": "Demo sequencer (Illumina)", "model": "Demo Illumina",
     "location": "/runs/demo-illumina", "exclusions": ["Thumbnail_Images", "*.png"]},
    {"name": "Demo sequencer (Nanopore)", "model": "Demo Nanopore",
     "location": "/runs/demo-nanopore", "exclusions": []},
    {"name": "Demo mass spectrometer (timsTOF)", "model": "Demo timsTOF",
     "location": "/runs/demo-proteomics", "exclusions": []},
]


def call(method: str, path: str, body=None, token=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def main() -> None:
    for _ in range(60):
        try:
            call("GET", "/auth/status")
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    else:
        sys.exit("backend did not start")

    token = call("POST", "/auth/login", {"username": USER, "password": PASSWORD})["access_token"]

    models = {m["name"]: m["uuid"] for m in call("GET", "/sequencers-types/?limit=100", token=token)["results"]}
    for m in MODELS:
        if m["name"] not in models:
            models[m["name"]] = call("POST", "/sequencers-types/", m, token)["uuid"]
            print(f"created instrument model {m['name']}")

    existing = {s["name"] for s in call("GET", "/sequencers/?limit=100", token=token)["results"]}
    for i in INSTRUMENTS:
        if i["name"] in existing:
            continue
        call("POST", "/sequencers/", {"name": i["name"], "location": i["location"],
                                      "type_uuid": models[i["model"]], "sent_to_tre": "auto",
                                      "exclusions": i["exclusions"]}, token)
        print(f"created instrument {i['name']} at {i['location']}")
    print("demo setup done")


if __name__ == "__main__":
    main()
