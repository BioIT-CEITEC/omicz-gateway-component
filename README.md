# Sequencer Gateway

A web application for managing DNA sequencer runs. It monitors sequencer output folders, detects when runs complete, generates checksums, and uploads run data to S3 storage automatically.

---

## What it does

- Watches configured sequencer machine output folders for new run folders
- Detects run completion via a **signal file** (e.g. `RTAComplete.txt`) or **file stability** (files stop growing)
- Generates a SHA256 checksum file for the run
- Uploads the run folder to S3
- Provides a web UI to manage sequencers, runs, and monitor status in real time

---

## Requirements

- [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/)
- Access to a Kubernetes cluster (for the S3 proxy via `kubectl port-forward`)

---

## Installation

### 1. Clone the repository

```bash
git clone git@github.com:BioIT-CEITEC/omicz-gateway-component.git
cd omicz-gateway-component
```

### 2. Create the environment file

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# ── Sequencer machine output folders ─────────────────────────────────────────
# Add one line per sequencer machine.
# Left side  = real path on THIS computer (host)
# Right side = name used in docker-compose.yml (must match)
#
# Linux / Mac:
MACHINE_1_PATH=/data/sequencers/illumina

# Windows:
# MACHINE_1_PATH=C:\Sequencer\Illumina
```

### 3. Configure docker-compose.yml

Open `docker-compose.yml` and add one volume line per sequencer machine to the `backend`, `worker`, and `watcher` services:

```yaml
volumes:
  - ./backend:/app
  - ${MACHINE_1_PATH}:/runs/machine-1     # add one line per machine
  - ${MACHINE_2_PATH}:/runs/machine-2     # optional: add more machines
```

> The right side (`/runs/machine-1`) is the path **inside the container** — always use `/runs/` prefix.
> The left side is the real path on your computer — set it in `.env`.

### 4. Build and start the services

```bash
docker compose up -d --build
```

### 5. Run database migrations

```bash
docker exec fastapi_gateway_backend alembic upgrade head
```

### 6. Open the web UI

| Service | URL |
|---------|-----|
| Frontend (main UI) | http://localhost:8001 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| RabbitMQ management | http://localhost:15672 (guest / guest) |
| Adminer (database UI) | http://localhost:8090 |

---

## Configuration

### Add a Sequencer Type

Go to **Sequencer Types → Create** and define how the sequencer signals run completion:

| Field | Description |
|-------|-------------|
| Name | Display name (e.g. `Illumina NovaSeq`) |
| Completion Method | `signal` — wait for a specific file to appear |
| | `file_stability` — wait for files to stop growing |
| Completion Signal | Filename to watch for (signal method only, e.g. `RTAComplete.txt`) |
| Signal Match | `exact`, `prefix`, or `suffix` |
| Stability Files | List of filenames to monitor for size changes (file_stability only) |
| Stability Threshold | Minutes of no growth before declaring run complete (default: 10) |

### Add a Sequencer

Go to **Sequencers → Create** and fill in:

| Field | Description |
|-------|-------------|
| Name | Display name (e.g. `Machine 7 - Illumina`) |
| Location | Path **inside the container** — always starts with `/runs/` (e.g. `/runs/machine-7`) |
| Type | Select the sequencer type you created above |
| Send to TRE | `auto` — upload automatically after run finishes; `manual` — wait for button click |
| Exclusions | Files/patterns to skip during upload (e.g. `*.png`, `Thumbnail_Images`) |

> After adding a sequencer, the watcher picks it up within 60 seconds — no restart needed.

---

## Adding a New Machine

When a new sequencer machine is connected:

1. **Add to `.env`:**
   ```env
   MACHINE_2_PATH=/data/sequencers/ont
   ```

2. **Add to `docker-compose.yml`** (backend, worker, watcher volumes):
   ```yaml
   - ${MACHINE_2_PATH}:/runs/machine-2
   ```

3. **Restart the stack:**
   ```bash
   docker compose down && docker compose up -d
   ```

4. **Create the sequencer in the UI** with location `/runs/machine-2`

---

## Kubernetes S3 Proxy

The app uploads runs to S3 through a `kubectl port-forward` tunnel. This is managed from the UI — no manual terminal commands needed.

### Setup

1. Go to **K8s Proxy** in the navigation bar
2. Fill in the connection details:
   - Namespace (e.g. `omicz-dev-ns`)
   - Service name (e.g. `omicz-dev-s3-proxy`)
   - Local port: `8080`
   - Remote port: `8080`
3. Paste your **kubeconfig** into the text area
4. Click **Save Config**
5. Click **Start**

The status badge turns green when the tunnel is active. Logs are shown live on the page.

> The backend container must be rebuilt after first install to have `kubectl` available:
> ```bash
> docker compose build backend && docker compose up -d backend
> ```

### S3 configuration

Add to `backend/.env`:

```env
# Required — points to the kubectl tunnel running inside the backend container
S3_ENDPOINT=http://backend:8080

# Optional — override only if your S3 setup differs from the defaults
# S3_ACCESS_KEY=your_access_key
# S3_SECRET_KEY=your_secret_key
# S3_BUCKET=your-bucket-name
# S3_REGION=us-east-1
# S3_PREFIX=raw_run_data/
```

---

## Run Status Flow

```
running → running_finished → checksumming → moving → verifying → completed
                                          ↘ move_failed        ↘ verify_failed
```

| Status | Meaning |
|--------|---------|
| `running` | Run folder detected, sequencing in progress |
| `running_finished` | Completion signal detected, waiting for upload |
| `checksumming` | Generating SHA256 checksum file |
| `moving` | Uploading folder to S3 |
| `verifying` | Waiting for TRE to confirm checksum |
| `completed` | Done |
| `move_failed` | Upload failed — use **Retry Upload** button |
| `verify_failed` | TRE verification failed — use **Retry Verification** or **Recheck & Re-upload** |

---

## Windows Notes

The app runs entirely inside Linux Docker containers — the Python code does not change for Windows. The only difference is the volume mount in `docker-compose.yml`:

```yaml
# Linux / Mac:
- /data/sequencers/machine-1:/runs/machine-1

# Windows:
- C:\Sequencer\Machine1:/runs/machine-1
```

Set the host path (left side) in `.env`. The container path (right side, `/runs/...`) is always the same regardless of OS.

---

## After Code Changes

| Change | Command |
|--------|---------|
| Python code (backend/frontend) | `docker restart fastapi_gateway_backend fastapi_gateway_frontend` |
| Worker or watcher code | `docker restart fastapi_gateway_worker fastapi_gateway_watcher` |
| New DB migration | `docker exec fastapi_gateway_backend alembic upgrade head` |
| Dockerfile changes | `docker compose build <service> && docker compose up -d <service>` |
