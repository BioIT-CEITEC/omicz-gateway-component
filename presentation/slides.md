# FastAPI as a Microservice Gateway
### Building an Async, Event-Driven Pipeline in Python

---

## Slide 1 — Title

**FastAPI as a Microservice Gateway**
Building an Async, Event-Driven Pipeline in Python

> A real-world project: automated tracking and post-processing of DNA sequencing machine output

---

## Slide 2 — Why FastAPI?

**FastAPI is a modern Python web framework built for speed and correctness**

Key strengths:
- **Async-first** — built on ASGI (Starlette), handles concurrent I/O natively
- **Type hints everywhere** — Python type annotations drive everything
- **Pydantic integration** — automatic request validation and serialization
- **Auto-generated docs** — OpenAPI (Swagger UI + ReDoc) out of the box
- **Dependency Injection** — clean, testable wiring of DB sessions, auth, config

> Performance comparable to Node.js and Go; roughly 3–5x faster than Flask/Django on I/O-bound workloads

---

## Slide 3 — System Architecture

**7 Docker Compose services working together**

```
[Frontend FastAPI :8001]  ──HTTP──►  [Backend FastAPI :8000]  ──SQL──►  [PostgreSQL :5432]
                                              │
                                        [RabbitMQ :5672]
                                         ▲          │
                                         │          ▼
                                    [Watcher]   [Worker]
                                    (watchdog)  (pika consumer)
                                         │          │
                                    [Filesystem]  [S3 / TRE]
```

| Service | Role |
|---|---|
| backend | FastAPI REST API — the gateway |
| frontend | FastAPI + Jinja2 — web UI |
| worker | RabbitMQ consumer, async processor |
| watcher | Filesystem monitor, event publisher |
| db | PostgreSQL 15 |
| rabbitmq | Message broker |

---

## Slide 4 — FastAPI Routing & Path Parameters

**Declarative, type-safe route definitions**

```python
# api/v1/runs.py
@router.get("/{uuid}", response_model=ShowRun)
def get_run(uuid: UUID, db: Session = Depends(get_db)):
    run = run_repo.get_run(db, uuid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run

@router.post("/{uuid}/start-upload", response_model=ShowRun)
def start_upload(uuid: UUID, db: Session = Depends(get_db)):
    run = run_repo.get_run(db, uuid)
    if run.status not in ("running_finished", "move_failed"):
        raise HTTPException(status_code=409, detail="Invalid state for upload")
    publisher.publish("run_checksum_requested", run.name, str(run.sequencer_uuid))
    return run
```

Key patterns:
- **UUID path params** — FastAPI validates and parses automatically
- **`Depends(get_db)`** — dependency injection for DB session lifecycle
- **`response_model`** — Pydantic schema controls exactly what is returned
- **`HTTPException`** — returns correct JSON error responses

---

## Slide 5 — Pydantic: Validation & Serialization

**Pydantic schemas are the contract between client and API**

```python
# schemas/sequencers.py
class SequencerCreate(BaseModel):
    name: str
    location: str
    sent_to_tre: Literal["auto", "manual"] = "manual"
    type_uuid: UUID

class ShowSequencer(BaseModel):
    uuid: UUID
    name: str
    slug: str
    status: str
    sent_to_tre: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# schemas/runs.py
class ShowRun(BaseModel):
    uuid: UUID
    name: str
    status: str
    sequencer_name: str       # joined field from relationship
    sequencer_sent_to_tre: str
```

- **`from_attributes=True`** — reads from SQLAlchemy ORM objects directly
- **Nested/computed fields** — `sequencer_name` is resolved from the ORM relationship
- **`Literal` types** — constrain values to an allowed set, validated before hitting the DB

---

## Slide 6 — Database Layer: SQLAlchemy + Repository Pattern

**FastAPI stays thin; DB logic lives in repositories**

```python
# db/models/runs.py
class Runs(Base):
    __tablename__ = "runs"
    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, index=True, default=uuid4)
    name = Column(String, nullable=False)
    sequencer_uuid = Column(UUID(as_uuid=True), ForeignKey("sequencers.uuid"))
    status = Column(String, default="running")

# db/repositories/runs.py
def update_run_status(db: Session, run_uuid: UUID, new_status: str) -> Runs:
    run = db.query(Runs).filter(Runs.uuid == run_uuid).first()
    run.status = new_status
    db.commit()
    db.refresh(run)
    return run
```

- **Dual PK pattern** — integer `id` (internal) + `uuid` (external API) on every table
- **Soft deletes** — `is_deleted=True` flag; never hard-delete rows
- **Repository pattern** — DB operations isolated from route handlers
- **Alembic** — schema migrations tracked in version files

---

## Slide 7 — Async Event-Driven Communication: RabbitMQ

**FastAPI publishes events; a separate worker consumes them**

```python
# services/publisher.py  (backend)
def publish(event: str, name: str, sequencer_uuid: str):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    message = json.dumps({"event": event, "name": name, "sequencer_uuid": sequencer_uuid})
    channel.basic_publish(exchange="", routing_key=QUEUE_NAME, body=message)
    connection.close()
```

**Event flow:**

```
watcher detects RTAComplete.txt
    → publishes  run_completed
        → worker sets status = running_finished
            → (if auto) publishes  run_checksum_requested
                → worker checksums folder
                    → publishes  run_upload_requested
                        → worker uploads to S3
                            → status = completed
```

- FastAPI is **not blocked** — publish is fire-and-forget
- Worker runs in a **separate container**, consumes at its own pace
- Each status transition is **recorded** in `runs_status_history`

---

## Slide 8 — Filesystem Watcher as an Event Source

**Bridging the physical world (sequencer machines) to the API**

```python
# services/watcher.py
class RunEventHandler(FileSystemEventHandler):
    def on_created(self, event):
        path = Path(event.src_path)
        if self.sequencer.is_completion_signal(path.name):
            run_name = path.parent.name
            publisher.publish("run_completed", run_name, str(self.sequencer.uuid))

observer = PollingObserver(timeout=10)   # PollingObserver — safe inside Docker on macOS
observer.schedule(handler, path=sequencer.location, recursive=True)
observer.start()
```

- **`watchdog` library** with `PollingObserver` — polls every 10 seconds
- **Configurable completion signal** — each sequencer type defines its own trigger file (e.g. `RTAComplete.txt`), with exact/prefix/suffix matching
- **Watcher polls the DB** every 60 seconds for newly added sequencers — no restart needed
- **Startup scan** — on boot, watcher checks for already-existing run folders to catch missed events

---

## Slide 9 — Two FastAPI Services: API + Frontend

**A clean split: one service owns data, one owns presentation**

```
backend/                          frontend/
├── api/v1/runs.py                ├── routers/runs.py
│   └── REST JSON API             │   └── calls backend via httpx
├── schemas/                      ├── templates/runs/
│   └── Pydantic contracts        │   └── Jinja2 HTML templates
├── db/                           └── main.py
│   └── SQLAlchemy + Alembic          └── mounts /static, registers routers
└── services/
    └── publisher, worker, watcher
```

- **Backend** — pure REST API, no HTML, no sessions; speaks JSON only
- **Frontend** — FastAPI acts as a server-side rendering layer; uses `httpx` to call the backend
- Both use **dependency injection**, **structured logging**, and **global exception handlers**
- Separation allows the backend to be consumed by other clients (CLI, other services) independently

---

## Slide 10 — Key Takeaways

**What makes this architecture work**

| Concern | Solution |
|---|---|
| Request validation | Pydantic schemas with type hints |
| DB access | SQLAlchemy + Repository pattern |
| Async processing | RabbitMQ + dedicated worker container |
| Physical event ingestion | watchdog filesystem monitor |
| Data integrity | Dual id/uuid PKs, soft deletes, status history log |
| Deployment | Docker Compose — all services orchestrated together |

**FastAPI's role as a gateway:**
- Validates and routes all incoming requests
- Enforces state machine rules (e.g. can only upload from `running_finished`)
- Decouples frontend from data layer
- Acts as the sole publisher into the async event pipeline

> The result: a fully automated pipeline from sequencer output to S3 upload, with a complete audit trail and a clean web UI — all in Python.
