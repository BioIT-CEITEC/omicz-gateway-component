"""Generate presentation.pptx — modern professional theme."""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# ── Palette ──────────────────────────────────────────────────────────────────
NAVY        = RGBColor(0x0F, 0x17, 0x2A)   # primary dark
NAVY_MID    = RGBColor(0x1E, 0x35, 0x5C)   # mid navy for cards
CYAN        = RGBColor(0x06, 0xB6, 0xD4)   # electric cyan accent
CYAN_DIM    = RGBColor(0xCC, 0xF1, 0xF8)   # very light cyan
AMBER       = RGBColor(0xF5, 0x9E, 0x0B)   # warm highlight
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
OFF_WHITE   = RGBColor(0xF8, 0xFA, 0xFC)
SLATE       = RGBColor(0x47, 0x55, 0x69)   # body text secondary
LIGHT_SLATE = RGBColor(0xE2, 0xE8, 0xF0)   # dividers / row fills
DARK_TEXT   = RGBColor(0x0F, 0x17, 0x2A)
CODE_BG     = RGBColor(0x0D, 0x1B, 0x2A)
CODE_FG     = RGBColor(0x67, 0xE8, 0xF9)   # bright cyan text

STUDENT_NAME = "Alireza Dantism"
USO_NUM      = "256649"
SUPERVISOR   = "Michal Batko"
COURSE       = "FI: PA053 Distributed Systems and Middleware (Spring 2026)"

prs = Presentation()
prs.slide_width  = Inches(13.33)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]

W = 13.33
H = 7.5


# ── Primitives ───────────────────────────────────────────────────────────────

def rect(slide, l, t, w, h, fill=None, line=None, lw=0.75):
    s = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
    if fill:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = line; s.line.width = Pt(lw)
    else:
        s.line.fill.background()
    return s


def txt(slide, text, l, t, w, h, size=16, bold=False, italic=False,
        color=DARK_TEXT, align=PP_ALIGN.LEFT, wrap=True):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = wrap
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = bold
    r.font.italic = italic; r.font.color.rgb = color
    return tb


def multiline(slide, lines, l, t, w, h, size=13, color=DARK_TEXT,
              mono=False, gap=0):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = False
    first = True
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        if gap: p.space_before = Pt(gap)
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.color.rgb = color
        if mono: r.font.name = "Courier New"


def bullets(slide, items, l, t, w, h, size=15):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    first = True
    for level, text in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_before = Pt(5 if level == 0 else 2)
        r = p.add_run()
        r.text = ("▸  " if level == 0 else "    ›  ") + text
        r.font.size = Pt(size if level == 0 else size - 1.5)
        r.font.color.rgb = DARK_TEXT if level == 0 else SLATE


def code_box(slide, code, l, t, w, h, size=10.5):
    rect(slide, l, t, w, h, fill=CODE_BG)
    # top cyan stripe
    rect(slide, l, t, w, 0.05, fill=CYAN)
    # line numbers gutter bg
    rect(slide, l, t+0.05, 0.38, h-0.05, fill=RGBColor(0x07, 0x10, 0x1A))
    tb = slide.shapes.add_textbox(
        Inches(l+0.42), Inches(t+0.1),
        Inches(w-0.48), Inches(h-0.15))
    tf = tb.text_frame; tf.word_wrap = False
    lines = code.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.color.rgb = CODE_FG
        r.font.name = "Courier New"
    # line numbers
    tb2 = slide.shapes.add_textbox(
        Inches(l+0.04), Inches(t+0.1), Inches(0.32), Inches(h-0.15))
    tf2 = tb2.text_frame; tf2.word_wrap = False
    for i in range(len(lines)):
        p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
        r = p.add_run(); r.text = str(i+1)
        r.font.size = Pt(size); r.font.color.rgb = RGBColor(0x33, 0x4A, 0x60)
        r.font.name = "Courier New"


def slide_header(slide, title, subtitle=None):
    """Navy top bar with white title, cyan underline."""
    rect(slide, 0, 0, W, 1.3, fill=NAVY)
    # cyan accent bar at very top (thin strip)
    rect(slide, 0, 0, W, 0.06, fill=CYAN)
    txt(slide, title, 0.45, 0.1, W-0.6, 0.72,
        size=27, bold=True, color=WHITE, align=PP_ALIGN.LEFT)
    if subtitle:
        txt(slide, subtitle, 0.45, 0.78, W-0.6, 0.44,
            size=12, italic=True, color=CYAN, align=PP_ALIGN.LEFT)
    # short cyan underline accent
    rect(slide, 0.45, 1.26, 1.8, 0.055, fill=CYAN)
    rect(slide, 2.27, 1.26, W-2.3, 0.055, fill=LIGHT_SLATE)


def slide_footer(slide, num, total=10):
    rect(slide, 0, H-0.3, W, 0.3, fill=NAVY)
    txt(slide,
        f"{STUDENT_NAME}  ·  USO {USO_NUM}  ·  Supervisor: {SUPERVISOR}  ·  {COURSE}",
        0.35, H-0.28, 11.5, 0.26, size=8, color=RGBColor(0x94, 0xA3, 0xB8))
    txt(slide, f"{num} / {total}", W-1.0, H-0.28, 0.85, 0.26,
        size=9, bold=True, color=CYAN, align=PP_ALIGN.RIGHT)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)

# full navy background
rect(slide, 0, 0, W, H, fill=NAVY)

# large diagonal decorative shape — bottom-right triangle effect via rectangles
# (simulate with a rotated parallelogram using overlapping rects at angle)
rect(slide, 8.2, 0, 5.13, H, fill=NAVY_MID)    # right panel
rect(slide, 9.5, 0, 3.83, H, fill=RGBColor(0x0A, 0x24, 0x45))  # deeper right

# cyan top strip
rect(slide, 0, 0, W, 0.07, fill=CYAN)
# cyan bottom strip
rect(slide, 0, H-0.07, W, 0.07, fill=CYAN)

# amber accent bar (left side highlight)
rect(slide, 0, 1.5, 0.07, 3.2, fill=AMBER)

# Main title
txt(slide, "FastAPI as a", 0.45, 1.2, 9.0, 0.9,
    size=44, bold=False, color=RGBColor(0xCB, 0xD5, 0xE1))
txt(slide, "Microservice Gateway",
    0.45, 2.0, 9.5, 1.1,
    size=52, bold=True, color=WHITE)

# cyan underline
rect(slide, 0.45, 3.15, 5.5, 0.065, fill=CYAN)

txt(slide, "Building an Async, Event-Driven Pipeline in Python",
    0.45, 3.35, 9.0, 0.55,
    size=17, italic=True, color=CYAN)

# Info card
rect(slide, 0.45, 4.25, 7.4, 2.15, fill=RGBColor(0x1E, 0x35, 0x5C))
rect(slide, 0.45, 4.25, 0.065, 2.15, fill=AMBER)

info = [
    f"Student:      {STUDENT_NAME}  (USO {USO_NUM})",
    f"Supervisor:   {SUPERVISOR}",
    f"Course:       {COURSE}",
]
multiline(slide, info, 0.62, 4.38, 7.1, 1.9,
          size=13, color=RGBColor(0xCB, 0xD5, 0xE1), mono=False, gap=6)

# page num
txt(slide, "1 / 10", W-1.0, H-0.3, 0.85, 0.28,
    size=9, bold=True, color=CYAN, align=PP_ALIGN.RIGHT)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — Why FastAPI?
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Why FastAPI?",
             "A modern Python web framework built for speed and correctness")

items = [
    (0, "Async-first — built on ASGI (Starlette), handles concurrent I/O natively"),
    (0, "Type hints everywhere — Python annotations drive validation, docs, and serialisation"),
    (0, "Pydantic integration — request validated automatically before your handler runs"),
    (0, "Auto-generated docs — OpenAPI (Swagger UI + ReDoc) at runtime, zero extra work"),
    (0, "Dependency Injection — clean, testable wiring of DB sessions, config, and auth"),
]
bullets(slide, items, 0.5, 1.45, 8.4, 3.9, size=17)

# performance card
rect(slide, 9.1, 1.45, 3.95, 3.5, fill=NAVY)
rect(slide, 9.1, 1.45, 3.95, 0.065, fill=CYAN)
txt(slide, "Performance", 9.3, 1.6, 3.6, 0.45,
    size=13, bold=True, color=CYAN)
txt(slide,
    "Comparable to\nNode.js and Go\n\n~3–5\u00d7 faster than\nFlask / Django\non I/O-bound workloads",
    9.3, 2.1, 3.5, 2.6, size=14, color=WHITE)

# quote band
rect(slide, 0.35, 5.55, W-0.7, 1.18, fill=CYAN_DIM)
rect(slide, 0.35, 5.55, 0.065, 1.18, fill=CYAN)
txt(slide,
    "\u201cIf your code imports FastAPI and Pydantic, you already have a contract, "
    "a validator, and a live documentation site \u2014 for free.\u201d",
    0.55, 5.65, W-1.0, 1.0, size=13.5, italic=True, color=SLATE)

slide_footer(slide, 2)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — System Architecture
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "System Architecture",
             "7 Docker Compose services orchestrated together")

C_BLUE   = NAVY
C_GREEN  = RGBColor(0x05, 0x7A, 0x55)
C_ORANGE = RGBColor(0xD9, 0x57, 0x06)
C_SLATE  = RGBColor(0x33, 0x45, 0x5E)

def svc(slide, label, l, t, w=2.1, h=0.82, col=C_BLUE):
    rect(slide, l, t, w, h, fill=col)
    rect(slide, l, t, w, 0.055, fill=CYAN)
    txt(slide, label, l+0.1, t+0.08, w-0.2, h-0.1,
        size=12, bold=True, color=WHITE, align=PP_ALIGN.CENTER, wrap=True)

svc(slide, "Frontend\nFastAPI :8001",   0.35, 1.48)
svc(slide, "Backend\nFastAPI :8000",    3.45, 1.48)
svc(slide, "PostgreSQL\n:5432",         6.55, 1.48, col=C_GREEN)
svc(slide, "RabbitMQ\n:5672",           3.45, 3.18, col=C_ORANGE)
svc(slide, "Watcher\n(watchdog)",       0.35, 4.88)
svc(slide, "Worker\n(pika consumer)",   6.55, 4.88)
svc(slide, "S3 / TRE",                 10.15, 4.88, w=1.9, col=C_GREEN)

for label, l, t in [
    ("HTTP (httpx)", 2.47, 1.8),
    ("SQL",          5.57, 1.8),
    ("pub/sub",      3.1,  2.42),
    ("events",       2.47, 4.18),
    ("consume",      5.57, 4.18),
    ("boto3 S3",     9.2,  5.1),
    ("Filesystem\n(sequencer output)", 0.35, 5.92),
]:
    txt(slide, label, l, t, 1.7, 0.55, size=10, italic=True,
        color=SLATE, align=PP_ALIGN.CENTER)

# legend
legend = [
    (C_BLUE,   "FastAPI service"),
    (C_GREEN,  "Storage / cloud"),
    (C_ORANGE, "Message broker"),
]
for i, (col, label) in enumerate(legend):
    lx = 9.6 + i*0.0
    ly = 1.5 + i*0.52
    rect(slide, 9.5, ly, 0.22, 0.3, fill=col)
    txt(slide, label, 9.78, ly, 2.8, 0.3, size=11, color=DARK_TEXT)

slide_footer(slide, 3)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — Routing
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "FastAPI Routing & Path Parameters",
             "Declarative, type-safe route definitions")

code = """\
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
        raise HTTPException(status_code=409, detail="Invalid state")
    publisher.publish("run_checksum_requested", run.name,
                      str(run.sequencer_uuid))
    return run"""

code_box(slide, code, 0.35, 1.42, 7.85, 4.9)

items = [
    (0, "UUID path params — parsed & validated automatically"),
    (0, "Depends(get_db) — DB session lifecycle via DI"),
    (0, "response_model — Pydantic filters the return value"),
    (0, "HTTPException — structured JSON error responses"),
    (0, "State machine enforced at the HTTP layer (409)"),
]
bullets(slide, items, 8.4, 1.42, 4.65, 4.9, size=14)

slide_footer(slide, 4)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — Pydantic
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Pydantic: Validation & Serialisation",
             "Schemas are the contract between client and API")

code = """\
# schemas/sequencers.py
class SequencerCreate(BaseModel):
    name: str
    location: str
    sent_to_tre: Literal["auto", "manual"] = "manual"
    type_uuid: UUID

class ShowSequencer(BaseModel):
    uuid: UUID
    name: str
    status: str
    sent_to_tre: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# schemas/runs.py
class ShowRun(BaseModel):
    uuid: UUID
    name: str
    status: str
    sequencer_name: str        # resolved via ORM relationship
    sequencer_sent_to_tre: str"""

code_box(slide, code, 0.35, 1.42, 7.7, 5.35)

items = [
    (0, 'Literal["auto","manual"] — rejected before hitting the DB'),
    (0, "from_attributes=True — reads SQLAlchemy ORM objects directly"),
    (0, "Joined field sequencer_name resolved via ORM relationship"),
    (0, "Separate Create vs Show — internal IDs never exposed"),
    (0, "422 Unprocessable Entity returned automatically on bad input"),
]
bullets(slide, items, 8.25, 1.42, 4.85, 4.8, size=14)

slide_footer(slide, 5)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — Database Layer
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Database Layer: SQLAlchemy + Repository Pattern",
             "FastAPI stays thin; all DB logic lives in repositories")

code = """\
# db/models/runs.py
class Runs(Base):
    __tablename__ = "runs"
    id             = Column(Integer, primary_key=True)
    uuid           = Column(UUID(as_uuid=True), unique=True,
                            index=True, default=uuid4)
    name           = Column(String, nullable=False)
    sequencer_uuid = Column(UUID(as_uuid=True),
                            ForeignKey("sequencers.uuid"))
    status         = Column(String, default="running")

# db/repositories/runs.py
def update_run_status(db, run_uuid, new_status):
    run = db.query(Runs).filter(Runs.uuid == run_uuid).first()
    run.status = new_status
    db.commit(); db.refresh(run)
    return run"""

code_box(slide, code, 0.35, 1.42, 7.7, 4.75)

items = [
    (0, "Dual PK — integer id (internal) + uuid (API surface)"),
    (0, "Soft deletes — is_deleted=True, rows are never removed"),
    (0, "Repository pattern — DB ops isolated from routes"),
    (0, "Alembic — versioned schema migrations"),
    (0, "runs_status_history — permanent timestamped audit log"),
]
bullets(slide, items, 8.25, 1.42, 4.85, 3.75, size=14)

# info card
rect(slide, 8.25, 5.05, 4.85, 1.62, fill=NAVY)
rect(slide, 8.25, 5.05, 4.85, 0.055, fill=AMBER)
txt(slide, "5 Tables", 8.45, 5.13, 4.5, 0.38, size=11, bold=True, color=AMBER)
txt(slide, "users  ·  sequencers  ·  sequencers_types\nruns  ·  runs_status_history",
    8.45, 5.48, 4.5, 0.65, size=11, color=WHITE)
txt(slide, "All tables: id (int PK) + uuid (UUID, unique, indexed)",
    8.45, 6.1, 4.5, 0.45, size=10, italic=True,
    color=RGBColor(0x94, 0xA3, 0xB8))

slide_footer(slide, 6)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — Async Events
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Async Event-Driven Communication",
             "FastAPI publishes events; a separate worker consumes them")

code = """\
# services/publisher.py
def publish(event: str, name: str, sequencer_uuid: str):
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    message = json.dumps({
        "event": event,
        "name": name,
        "sequencer_uuid": sequencer_uuid
    })
    channel.basic_publish(
        exchange="", routing_key=QUEUE_NAME, body=message)
    connection.close()"""

code_box(slide, code, 0.35, 1.42, 6.8, 4.15)

# pipeline flow panel
rect(slide, 7.35, 1.42, 5.65, 4.15, fill=CODE_BG)
rect(slide, 7.35, 1.42, 5.65, 0.055, fill=AMBER)
txt(slide, "Event Pipeline", 7.5, 1.5, 5.3, 0.38,
    size=11, bold=True, color=AMBER)
flow = [
    "watcher detects RTAComplete.txt",
    "  -> publishes  run_completed",
    "      -> worker: status = running_finished",
    "          -> publishes  run_checksum_requested",
    "              -> worker: checksums folder",
    "                  -> publishes  run_upload_requested",
    "                      -> worker: S3 upload",
    "                          -> status = completed",
]
multiline(slide, flow, 7.5, 1.88, 5.35, 3.55,
          size=10.5, color=CODE_FG, mono=True, gap=2)

items = [
    (0, "HTTP response is instant — publish is fire-and-forget"),
    (0, "Worker is a separate container and scales independently"),
    (0, "Every status transition recorded in runs_status_history"),
]
bullets(slide, items, 0.35, 5.77, W-0.7, 1.2, size=15)

slide_footer(slide, 7)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — Filesystem Watcher
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Filesystem Watcher as an Event Source",
             "Bridging physical sequencer machines to the event pipeline")

code = """\
# services/watcher.py
class RunEventHandler(FileSystemEventHandler):
    def on_created(self, event):
        path = Path(event.src_path)
        if self.sequencer.is_completion_signal(path.name):
            run_name = path.parent.name
            publisher.publish(
                "run_completed",
                run_name,
                str(self.sequencer.uuid))

observer = PollingObserver(timeout=10)
observer.schedule(handler,
                  path=sequencer.location,
                  recursive=True)
observer.start()"""

code_box(slide, code, 0.35, 1.42, 7.1, 4.85)

items = [
    (0, "watchdog library with PollingObserver"),
    (1, "Polls every 10 s — reliable inside Docker on macOS"),
    (0, "Configurable completion signal per sequencer type"),
    (1, "exact / prefix / suffix matching  (e.g. RTAComplete.txt)"),
    (0, "Polls DB every 60 s for newly added sequencers"),
    (1, "No container restart needed after adding a sequencer"),
    (0, "Startup scan — catches runs that appeared while offline"),
]
bullets(slide, items, 7.65, 1.42, 5.45, 4.85, size=14)

slide_footer(slide, 8)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — Two FastAPI Services
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Two FastAPI Services: API + Frontend",
             "A clean split: one service owns data, one owns presentation")

# Backend card — navy
rect(slide, 0.35, 1.42, 5.9, 5.32, fill=NAVY)
rect(slide, 0.35, 1.42, 5.9, 0.055, fill=CYAN)
txt(slide, "Backend  :8000", 0.55, 1.53, 5.6, 0.48,
    size=16, bold=True, color=CYAN)
be = [
    "api/v1/runs.py",
    "  REST JSON API only",
    "schemas/",
    "  Pydantic contracts",
    "db/",
    "  SQLAlchemy + Alembic",
    "services/",
    "  publisher, worker, watcher",
    "",
    "Speaks JSON only.",
    "No HTML. No sessions.",
    "Any client can consume it.",
]
multiline(slide, be, 0.55, 2.02, 5.55, 4.55, size=12.5,
          color=RGBColor(0xCB, 0xD5, 0xE1), mono=True, gap=2)

# HTTP label
txt(slide, "HTTP\n(httpx)", 6.38, 3.75, 0.67, 0.72,
    size=10, italic=True, color=CYAN, align=PP_ALIGN.CENTER)

# Frontend card — navy mid (slightly different shade)
rect(slide, 7.08, 1.42, 5.9, 5.32, fill=NAVY_MID)
rect(slide, 7.08, 1.42, 5.9, 0.055, fill=AMBER)
txt(slide, "Frontend  :8001", 7.28, 1.53, 5.6, 0.48,
    size=16, bold=True, color=AMBER)
fe = [
    "routers/runs.py",
    "  calls backend via httpx",
    "templates/runs/",
    "  Jinja2 HTML templates",
    "main.py",
    "  mounts /static, registers routers",
    "",
    "Server-side rendering.",
    "No DB connection.",
    "Replace with React — backend",
    "stays unchanged.",
]
multiline(slide, fe, 7.28, 2.02, 5.55, 4.55, size=12.5,
          color=RGBColor(0xCB, 0xD5, 0xE1), mono=True, gap=2)

slide_footer(slide, 9)


# ════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — Key Takeaways
# ════════════════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(BLANK)
rect(slide, 0, 0, W, H, fill=OFF_WHITE)
slide_header(slide, "Key Takeaways",
             "What makes FastAPI the right choice as a gateway")

table_rows = [
    ("Request validation",    "Pydantic schemas with Python type hints"),
    ("DB access",             "SQLAlchemy + Repository pattern"),
    ("Async processing",      "RabbitMQ + dedicated worker container"),
    ("Physical event source", "watchdog filesystem monitor"),
    ("Data integrity",        "Dual id/uuid PKs  ·  soft deletes  ·  status history"),
    ("Deployment",            "Docker Compose — all services orchestrated"),
]

rh = 0.5
cw0, cw1 = 3.9, 8.6
tl, tt = 0.35, 1.45

# header row
rect(slide, tl, tt, cw0+cw1, rh, fill=NAVY)
rect(slide, tl, tt, cw0+cw1, 0.055, fill=CYAN)
txt(slide, "Concern",  tl+0.15, tt+0.1, cw0-0.15, rh-0.1,
    size=13, bold=True, color=CYAN)
txt(slide, "Solution", tl+cw0+0.15, tt+0.1, cw1-0.15, rh-0.1,
    size=13, bold=True, color=CYAN)

ROW_A = RGBColor(0xF0, 0xF4, 0xF8)
ROW_B = WHITE
for i, (concern, solution) in enumerate(table_rows):
    y = tt + rh*(i+1)
    bg = ROW_A if i % 2 == 0 else ROW_B
    rect(slide, tl,     y, cw0, rh, fill=bg, line=LIGHT_SLATE, lw=0.4)
    rect(slide, tl+cw0, y, cw1, rh, fill=bg, line=LIGHT_SLATE, lw=0.4)
    # cyan left micro-bar on concern col
    rect(slide, tl, y, 0.05, rh, fill=CYAN)
    txt(slide, concern,  tl+0.15, y+0.09, cw0-0.15, rh-0.1,
        size=13, bold=True, color=DARK_TEXT)
    txt(slide, solution, tl+cw0+0.15, y+0.09, cw1-0.15, rh-0.1,
        size=13, color=SLATE)

# closing quote band
rect(slide, 0.35, 5.78, W-0.7, 1.12, fill=NAVY)
rect(slide, 0.35, 5.78, W-0.7, 0.055, fill=AMBER)
txt(slide,
    "FastAPI stays thin — validate inputs, enforce state rules, publish events, return JSON. "
    "The async pipeline handles the rest. The result: a fully automated, auditable pipeline in Python.",
    0.55, 5.87, W-1.0, 0.95, size=13, italic=True,
    color=RGBColor(0xCB, 0xD5, 0xE1))

slide_footer(slide, 10)


# ── Save ─────────────────────────────────────────────────────────────────────
out = "/Users/alireza/Documents/-omicz-/fastapi_gateway/presentation/presentation.pptx"
prs.save(out)
print(f"Saved: {out}")
