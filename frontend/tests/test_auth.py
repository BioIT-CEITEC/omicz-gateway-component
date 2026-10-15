"""The login middleware: redirects, silent refresh, token forwarding to the backend, cross-site POSTs."""
import os
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
import backend_api

TOKENS = {"access_token": "new-access", "refresh_token": "new-refresh", "access_expires_in": 900, "refresh_expires_in": 604800}
USER = {"uuid": "u-1", "username": "alice", "is_admin": False, "is_active": True}


@pytest.fixture
def app(monkeypatch):
    sent = []   # Authorization headers the pages sent to the backend
    monkeypatch.setattr(auth, "_me", lambda access: USER if access in ("good-access", "new-access") else None)
    monkeypatch.setattr(auth, "_refresh", lambda refresh: TOKENS if refresh == "good-refresh" else None)
    monkeypatch.setattr(auth, "needs_setup", lambda: False)
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, **kw: sent.append((headers or {}).get("Authorization"))
                        or httpx.Response(200, json={}))

    a = FastAPI()
    a.add_middleware(auth.AuthMiddleware)

    @a.get("/page")                 # a sync page, like the real routers (runs in a worker thread)
    def page():
        backend_api.get("http://backend/runs/")
        return {"ok": True}

    @a.post("/change")
    def change():
        return {"ok": True}

    a.state.sent = sent
    return a


def client(app, **cookies):
    c = TestClient(app, follow_redirects=False)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


def test_page_without_session_redirects_to_login(app):
    r = client(app).get("/page?x=1", headers={"Accept": "text/html"})
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fpage%3Fx%3D1"


def test_page_redirects_to_setup_while_no_account_exists(app, monkeypatch):
    monkeypatch.setattr(auth, "needs_setup", lambda: True)
    r = client(app).get("/page", headers={"Accept": "text/html"})
    assert r.headers["location"] == "/setup"


def test_json_call_without_session_gets_401(app):
    r = client(app).get("/page")
    assert r.status_code == 401 and r.json()["login"].startswith("/login")


def test_valid_session_forwards_the_token_to_the_backend(app):
    r = client(app, omicz_access="good-access").get("/page")
    assert r.status_code == 200
    assert app.state.sent == ["Bearer good-access"]
    assert "set-cookie" not in r.headers


def test_expired_access_token_is_refreshed_silently(app):
    r = client(app, omicz_access="expired", omicz_refresh="good-refresh").get("/page")
    assert r.status_code == 200
    assert app.state.sent == ["Bearer new-access"]         # this request already uses the new token
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("omicz_access=new-access") and "HttpOnly" in c and "samesite=lax" in c.lower() for c in cookies)
    assert any(c.startswith("omicz_refresh=new-refresh") for c in cookies)


def test_expired_refresh_token_logs_out(app):
    r = client(app, omicz_access="expired", omicz_refresh="revoked").get("/page", headers={"Accept": "text/html"})
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_cross_site_post_is_refused(app):
    c = client(app, omicz_access="good-access")
    assert c.post("/change", headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.post("/change", headers={"Origin": "http://testserver"}).status_code == 200
    assert c.post("/change").status_code == 200   # no Origin header (e.g. curl): same-site cookies still required


def test_token_is_not_left_behind_after_the_request(app):
    client(app, omicz_access="good-access").get("/page")
    assert backend_api.access_token.get() is None


@pytest.mark.parametrize("target,expected", [
    ("/runs", "/runs"), ("//evil.com", "/"), ("/\\evil.com", "/"), ("https://evil.com", "/"), ("", "/"), (None, "/"),
])
def test_login_only_redirects_to_local_paths(target, expected):
    assert auth._safe_next(target) == expected


def test_secure_cookies_follow_https(monkeypatch):
    class R:
        def __init__(self, scheme, proto=""):
            self.url = type("U", (), {"scheme": scheme})()
            self.headers = {"x-forwarded-proto": proto}
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert auth._secure(R("https")) and auth._secure(R("http", "https")) and not auth._secure(R("http"))
    monkeypatch.setenv("COOKIE_SECURE", "true")
    assert auth._secure(R("http"))
