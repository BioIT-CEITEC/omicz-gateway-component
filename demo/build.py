"""Build a static, clickable demo of the OmiCZ Gateway web interface.

Renders the real frontend (FastAPI + Jinja2 templates) against a mock backend
filled with sample data (demo_data.py), and writes plain HTML that GitHub Pages
can serve. Links are made relative, the JSON endpoints that pages poll are
written as files, and actions (forms, POST/PUT requests) are disabled.

Usage (from the repository root, with the frontend requirements installed):
    python demo/build.py            # writes docs/
    python demo/build.py out_dir
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FRONTEND = REPO / "frontend"
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO / "docs"
REPO_URL = "https://github.com/BioIT-CEITEC/omicz-gateway-component"

sys.path.insert(0, str(HERE))
import demo_data as D  # noqa: E402

# ── Load the real frontend with a mock backend ────────────────────────────────
os.environ["BACKEND_URL"] = "http://backend.demo"
sys.path.insert(0, str(FRONTEND))
os.chdir(FRONTEND)  # templates/ and static/ are relative to the frontend folder

import logger as fe_logger  # noqa: E402
fe_logger.LOGS_BASE_DIR = tempfile.mkdtemp(prefix="omicz-demo-logs-")

import httpx  # noqa: E402


def _json(status: int, data) -> httpx.Response:
    return httpx.Response(status, json=data, request=httpx.Request("GET", "http://backend.demo"))


def _paginated(rows: list, params: dict) -> dict:
    skip, limit = int(params.get("skip", 0)), int(params.get("limit", 50))
    return {"total": len(rows), "skip": skip, "limit": limit, "results": rows[skip:skip + limit]}


def mock_backend(method: str, url: str, params=None, **_):
    """Answer the frontend's backend calls from demo_data."""
    if method != "GET":
        return _json(403, {"detail": "Demo mode: changes are disabled"})
    path = urlsplit(url).path.rstrip("/")
    p = dict(params or {})
    parts = path.strip("/").split("/")
    head, rest = parts[0], parts[1:]

    if head == "runs":
        if not rest:
            return _json(200, D.runs_page(p))
        if rest == ["queue"]:
            return _json(200, D.queue_page())
        if rest == ["failed"]:
            return _json(200, [r for r in D.RUNS if r["status"] in D.FAILED_STATES])
        if rest == ["active-transfers"]:
            active = [r for r in D.RUNS if r["status"] in ("checksumming", "moving")]
            return _json(200, {"count": len(active), "runs": [{"name": r["name"], "status": r["status"]} for r in active],
                               "directories": []})
        run = D.R.get(rest[0])
        if run is None:
            return _json(404, {"detail": "Run not found"})
        if rest[1:] == ["history"]:
            return _json(200, D.HISTORY[run["uuid"]])
        if rest[1:] == ["directories"]:
            return _json(200, D.DIRECTORIES[run["uuid"]])
        return _json(200, run)

    if head == "sequencers":
        if not rest:
            return _json(200, _paginated(D.SEQUENCERS, p))
        if rest == ["mount-status"]:
            return _json(200, D.MOUNT_STATUS)
        seq = D.S.get(next((s["name"] for s in D.SEQUENCERS if s["uuid"] == rest[0]), ""))
        return _json(200, seq) if seq else _json(404, {"detail": "Instrument not found"})

    if head == "sequencers-types":
        if not rest:
            return _json(200, _paginated(D.TYPES, p))
        st = next((t for t in D.TYPES if t["uuid"] == rest[0]), None)
        return _json(200, st) if st else _json(404, {"detail": "Instrument model not found"})

    if head == "settings":
        if not rest:
            return _json(200, D.SETTINGS)
        s = next((s for s in D.SETTINGS if s["key"] == rest[0]), None)
        return _json(200, s) if s else _json(404, {"detail": "Setting not found"})

    if head == "logs":
        services = sorted(k for k in D.LOGS if k != "frontend")
        if not rest:
            return _json(200, {"services": services})
        return _json(200, {"service": rest[0], "lines": D.LOGS.get(rest[0], [])})

    return _json(404, {"detail": "Not found"})


httpx.get = lambda url, params=None, **kw: mock_backend("GET", url, params, **kw)
httpx.post = lambda url, **kw: mock_backend("POST", url, **kw)
httpx.put = lambda url, **kw: mock_backend("PUT", url, **kw)
httpx.patch = lambda url, **kw: mock_backend("PATCH", url, **kw)
httpx.delete = lambda url, **kw: mock_backend("DELETE", url, **kw)

import shared_templates  # noqa: E402
shared_templates._read_version = lambda: D.VERSION

from main import app  # noqa: E402
from routers import containers as r_containers, logs as r_logs  # noqa: E402
r_containers._fetch_containers = lambda: D.CONTAINERS
r_logs._frontend_log_lines = lambda n: D.LOGS["frontend"][-n:]

from fastapi.testclient import TestClient  # noqa: E402
client = TestClient(app)


# ── Routes → files ────────────────────────────────────────────────────────────
def canonical(url: str) -> str:
    """Normalise a URL with its query, ignoring paging and sort order. Mirrored in SHIM (JS)."""
    u = urlsplit(url)
    path = u.path if u.path.endswith("/") else u.path + "/"
    q = sorted((k, v) for k, v in parse_qsl(u.query) if k not in ("skip", "limit", "order"))
    return path + ("?" + "&".join(f"{k}={v}" for k, v in q) if q else "")


def out_file(url: str) -> str:
    u = urlsplit(url)
    q = dict(parse_qsl(u.query))
    path = u.path.strip("/")
    if path == "logs" and "service" in q:
        path = f"logs/{q['service']}"
    elif path == "acquisition-runs" and "sequencer_uuid" in q:
        path = f"acquisition-runs/instrument/{q['sequencer_uuid']}"
    elif path == "acquisition-runs" and "status" in q:
        statuses = sorted(v for k, v in parse_qsl(u.query) if k == "status")
        path = "acquisition-runs/status/" + "-".join(s.replace("_", "") for s in statuses)
    return f"{path}/index.html" if path else "index.html"


FAILED_LINK = "/acquisition-runs/?status=move_failed&status=verify_failed&status=failed&status=transfer_conflict"
PAGES = ["/", "/instruments/", "/instruments/create", "/instrument-models/", "/instrument-models/create",
         "/acquisition-runs/", "/acquisition-runs/queue/view", "/containers/", "/settings/", "/logs/", "/changelog/",
         "/acquisition-runs/?status=running", "/acquisition-runs/?status=running_finished",
         "/acquisition-runs/?status=completed", FAILED_LINK]
PAGES += [f"/instruments/{s['uuid']}" for s in D.SEQUENCERS] + [f"/instruments/{s['uuid']}/edit" for s in D.SEQUENCERS]
PAGES += [f"/acquisition-runs/?sequencer_uuid={s['uuid']}" for s in D.SEQUENCERS]
PAGES += [f"/instrument-models/{t['uuid']}" for t in D.TYPES] + [f"/instrument-models/{t['uuid']}/edit" for t in D.TYPES]
PAGES += [f"/acquisition-runs/{r['uuid']}" for r in D.RUNS]
PAGES += [f"/logs/?service={s}" for s in D.LOGS]

# JSON endpoints that pages fetch from the browser → api/<path>.json
API = {"/system/version": D.SYSTEM_VERSION}
for path in ["/containers/data"] + [f"/logs/data/{s}" for s in D.LOGS] + \
            [f"/acquisition-runs/{r['uuid']}/history-data" for r in D.RUNS]:
    res = client.get(path)
    res.raise_for_status()
    API[path] = res.json()

ROUTES = {canonical(u): out_file(u) for u in PAGES}

SHIM = """<script data-demo-base="{base}">
(function () {
  var BASE = document.currentScript.getAttribute('data-demo-base');
  var ROUTES = {routes};
  function canonical(url) {
    var u = new URL(url, 'https://demo.local');
    var path = u.pathname.endsWith('/') ? u.pathname : u.pathname + '/';
    var q = [];
    u.searchParams.forEach(function (v, k) { if (['skip', 'limit', 'order'].indexOf(k) < 0) q.push([k, v]); });
    q.sort(function (a, b) { return a[0] === b[0] ? (a[1] < b[1] ? -1 : 1) : (a[0] < b[0] ? -1 : 1); });
    return path + (q.length ? '?' + q.map(function (p) { return p[0] + '=' + p[1]; }).join('&') : '');
  }
  function toast(msg) {
    var el = document.getElementById('demo-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'demo-toast';
      el.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:9999;background:#0C2461;color:#fff;' +
        'padding:10px 18px;border-radius:10px;font:500 13px system-ui,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.25);transition:opacity .3s';
      document.body.appendChild(el);
    }
    el.textContent = msg; el.style.opacity = '1';
    clearTimeout(el._t); el._t = setTimeout(function () { el.style.opacity = '0'; }, 3200);
  }
  window.__demoNav = function (url) {
    var target = ROUTES[canonical(url)] || ROUTES[canonical(url.split('?')[0])];
    if (url.indexOf('?') >= 0 && !ROUTES[canonical(url)]) toast('Demo: this filter is not pre-rendered — showing all runs.');
    if (target) setTimeout(function () { location.href = BASE + target; }, ROUTES[canonical(url)] ? 0 : 900);
  };
  var realFetch = window.fetch.bind(window);
  window.fetch = function (input, opts) {
    var url = typeof input === 'string' ? input : input.url;
    var method = ((opts && opts.method) || 'GET').toUpperCase();
    if (method !== 'GET') {
      toast('Demo: actions are disabled in this static preview.');
      var body = JSON.stringify({ success: false, detail: 'Demo mode: actions are disabled', error: 'Demo mode: actions are disabled' });
      return Promise.resolve(new Response(body, { status: 403, headers: { 'Content-Type': 'application/json' } }));
    }
    if (url.charAt(0) === '/') return realFetch(BASE + 'api' + url.split('?')[0].replace(/\\/$/, '') + '.json');
    return realFetch(input, opts);
  };
  function handleSubmit(f) {
    if ((f.getAttribute('method') || 'get').toLowerCase() === 'get' && f.getAttribute('data-demo-path')) {
      var params = new URLSearchParams(new FormData(f)).toString();
      window.__demoNav(f.getAttribute('data-demo-path') + (params ? '?' + params : ''));
    } else {
      toast('Demo: actions are disabled in this static preview.');
    }
  }
  document.addEventListener('submit', function (e) {
    e.preventDefault(); e.stopPropagation();
    handleSubmit(e.target);
  }, true);
  HTMLFormElement.prototype.submit = function () { handleSubmit(this); };
})();
</script>"""

BADGE = f"""<a href="{REPO_URL}" target="_blank" rel="noopener"
  style="position:fixed;right:16px;bottom:16px;z-index:9998;background:#FFF8E1;color:#5D4300;border:1px solid #E8C870;
  padding:6px 12px;border-radius:999px;font:500 12px system-ui,sans-serif;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.12)">
  Demo · sample data · actions disabled · view on GitHub ↗</a>"""

ATTR = re.compile(r'\b(href|src|action)="(/[^"]*)"')


def rewrite(html: str, page: str) -> str:
    base = "../" * page.count("/")

    def fix(m):
        attr, url = m.group(1), m.group(2)
        if url.startswith("/static/"):
            return f'{attr}="{base}{url[1:]}"'
        if attr == "action":
            # GET forms (run filters) are handled by the shim; everything else is blocked on submit
            return f'{attr}="#" data-demo-path="{url}"'
        if "${" in url or "{{" in url:  # built in JS at runtime: keep the path, drop the query
            return f'{attr}="{base}{url.split("?")[0].strip("/")}/index.html"'
        target = ROUTES.get(canonical(url)) or ROUTES.get(canonical(url.split("?")[0]))
        if target is None:
            return f'{attr}="{base}{out_file(url.split("?")[0])}"'
        return f'{attr}="{base}{target}"'

    html = ATTR.sub(fix, html)
    html = re.sub(r"(?:window\.)?location\.href = ('/acquisition-runs/\?' \+ params\.toString\(\))",
                  r"window.__demoNav(\1)", html)
    shim = SHIM.replace("{base}", base).replace("{routes}", json.dumps(ROUTES))
    html = html.replace("<head>", "<head>\n" + shim, 1)
    return html.replace("</body>", BADGE + "\n</body>", 1)


# ── Build ─────────────────────────────────────────────────────────────────────
def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(FRONTEND / "static", OUT / "static", ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    (OUT / ".nojekyll").write_text("")

    for url in PAGES:
        res = client.get(url)
        if res.status_code != 200:
            raise SystemExit(f"{url} → HTTP {res.status_code}")
        page = out_file(url)
        (OUT / page).parent.mkdir(parents=True, exist_ok=True)
        (OUT / page).write_text(rewrite(res.text, page))

    res = client.get("/this-page-does-not-exist")
    (OUT / "404.html").write_text(rewrite(res.text, "404.html"))

    for path, data in API.items():
        f = OUT / ("api" + path + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, default=str))

    print(f"wrote {len(PAGES) + 1} pages and {len(API)} JSON files to {OUT}")


if __name__ == "__main__":
    main()
