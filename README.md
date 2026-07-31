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
- S3 storage credentials (endpoint URL, access key, secret key)

---

## Installation

### 1. Clone the repository

```bash
git clone git@github.com:BioIT-CEITEC/omicz-gateway-component.git
cd omicz-gateway-component
```

### 2. Create the root environment file

```bash
cp .env.example .env
```

Edit `.env` and set the real path to your sequencer machine output folder on this computer:

```env
# Linux / Mac:
MACHINE_1_PATH=/data/sequencers/machine-1

# Windows:
# MACHINE_1_PATH=C:\Sequencer\Machine1
```

### 3. Create the docker-compose file

```bash
cp docker-compose.example.yml docker-compose.yml
```

The example file is pre-configured for one machine (`MACHINE_1_PATH`). If you have more machines, add a volume line for each one in the `backend`, `worker`, and `watcher` services:

```yaml
volumes:
  - ./backend:/app
  - ${MACHINE_1_PATH}:/runs/machine-1     # already there
  - ${MACHINE_2_PATH}:/runs/machine-2     # add for each extra machine
```

> The right side (`/runs/machine-1`) is the path **inside the container** — always use `/runs/` prefix.
> The left side is the real path on your computer — set it in `.env`.

### 4. Create the backend environment file

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in your S3 credentials:

```env
S3_ENDPOINT=https://your-s3-proxy-url
S3_ACCESS_KEY=your_access_key
S3_SECRET_KEY=your_secret_key
S3_BUCKET=your-bucket-name
```

### 5. Build and start the services

```bash
docker compose up -d --build
```

### 6. Run database migrations

```bash
docker exec fastapi_gateway_backend alembic upgrade head
```

### 7. Open the web UI

| Service | URL |
|---------|-----|
| Frontend (main UI) | http://localhost:8001 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| RabbitMQ management | http://localhost:15672 (guest / guest) |
| Adminer (database UI) | http://localhost:8090 |

---

## First-time setup in the UI

### 1. Create a Sequencer Type

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

### 2. Create a Sequencer

Go to **Sequencers → Create** and fill in:

| Field | Description |
|-------|-------------|
| Name | Display name (e.g. `Machine 1 - Illumina`) |
| Location | Path **inside the container** — always starts with `/runs/` (e.g. `/runs/machine-1`) |
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
| `verify_failed` | TRE verification failed — use **Retry Verification** button |

---

## Windows Notes

The app runs entirely inside Linux Docker containers — the Python code does not change for Windows. The only difference is the volume mount syntax and the Docker socket path.

In `docker-compose.yml`, for the Docker socket:
```yaml
# Linux / macOS:
- /var/run/docker.sock:/var/run/docker.sock

# Windows (Docker Desktop) — use this instead:
- //var/run/docker.sock:/var/run/docker.sock
```

For machine paths in `.env`, use Windows format:
```env
MACHINE_1_PATH=C:\Sequencer\Machine1
```

---

## After Code Changes

| Change | Command |
|--------|---------|
| Python code (backend/frontend) | `docker restart fastapi_gateway_backend fastapi_gateway_frontend` |
| Worker or watcher code | `docker restart fastapi_gateway_worker fastapi_gateway_watcher` |
| New DB migration | `docker exec fastapi_gateway_backend alembic upgrade head` |
| Dockerfile changes | `docker compose build <service> && docker compose up -d <service>` |
| Settings changed in UI | No restart needed — applied at runtime |
