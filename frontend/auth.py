"""
Login for the web interface.

The backend issues an access token (15 min) and a refresh token (7 days); both are kept in
HttpOnly, SameSite=Lax cookies, Secure when the page is served over HTTPS. On every request the
middleware asks the backend who the access token belongs to; if it has expired, it uses the
refresh token to get a new pair and sends the new cookies with the response. Without a valid
session, pages redirect to /login (or to /setup while no account exists) and JSON calls get 401.
"""
import os
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

import backend_api
from logger import get_logger
from shared_templates import templates

logger = get_logger("frontend")

BACKEND_URL    = os.getenv("BACKEND_URL", "http://localhost:8000")
ACCESS_COOKIE  = "omicz_access"
REFRESH_COOKIE = "omicz_refresh"
PUBLIC_PATHS   = ("/login", "/setup", "/logout")
SAFE_METHODS   = ("GET", "HEAD", "OPTIONS")


@dataclass
class Session:
    user: dict
    access_token: str
    new_tokens: dict | None = None   # set when the session was refreshed during this request


# ── Talking to the backend ────────────────────────────────────────────────────
def _me(access: str) -> dict | None:
    try:
        r = httpx.get(f"{BACKEND_URL}/auth/me", headers={"Authorization": f"Bearer {access}"}, timeout=5)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def _refresh(refresh: str) -> dict | None:
    try:
        r = httpx.post(f"{BACKEND_URL}/auth/refresh", json={"refresh_token": refresh}, timeout=5)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def needs_setup() -> bool:
    try:
        return bool(httpx.get(f"{BACKEND_URL}/auth/status", timeout=5).json().get("needs_setup"))
    except Exception:
        return False


def resolve_session(access: str | None, refresh: str | None) -> Session | None:
    """The user behind the cookies, refreshing the tokens once if the access token has expired."""
    if access:
        user = _me(access)
        if user:
            return Session(user, access)
    if refresh:
        tokens = _refresh(refresh)
        if tokens:
            user = _me(tokens["access_token"])
            if user:
                return Session(user, tokens["access_token"], tokens)
    return None


# ── Cookies ───────────────────────────────────────────────────────────────────
def _secure(request: Request) -> bool:
    forced = os.getenv("COOKIE_SECURE", "").lower()
    if forced in ("true", "1", "yes"):
        return True
    if forced in ("false", "0", "no"):
        return False
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def set_session_cookies(response, tokens: dict, request: Request):
    common = dict(httponly=True, samesite="lax", secure=_secure(request), path="/")
    response.set_cookie(ACCESS_COOKIE, tokens["access_token"], max_age=tokens["access_expires_in"], **common)
    response.set_cookie(REFRESH_COOKIE, tokens["refresh_token"], max_age=tokens["refresh_expires_in"], **common)


def clear_session_cookies(response):
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def _safe_next(target: str | None) -> str:
    """Only local paths, so the login form cannot be used to redirect to another site."""
    if not target or not target.startswith("/") or target.startswith("//") or target.startswith("/\\"):
        return "/"
    return target


def _wants_html(request: Request) -> bool:
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


# ── Middleware ────────────────────────────────────────────────────────────────
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/static/") or path in PUBLIC_PATHS:
            return await call_next(request)

        # cookies ride along on cross-site requests in old browsers; refuse a state change from another origin
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)

        session = await run_in_threadpool(resolve_session, request.cookies.get(ACCESS_COOKIE),
                                          request.cookies.get(REFRESH_COOKIE))
        if session is None:
            if await run_in_threadpool(needs_setup):
                target = "/setup"
            else:
                target = "/login?next=" + quote(path + (f"?{request.url.query}" if request.url.query else ""), safe="")
            if _wants_html(request):
                response = RedirectResponse(target, status_code=303)
            else:
                response = JSONResponse({"detail": "Not logged in", "login": target}, status_code=401)
            clear_session_cookies(response)
            return response

        request.state.user = session.user
        token = backend_api.access_token.set(session.access_token)
        try:
            response = await call_next(request)
        finally:
            backend_api.access_token.reset(token)
        if session.new_tokens:
            set_session_cookies(response, session.new_tokens, request)
        return response


def require_admin(request: Request):
    user = getattr(request.state, "user", None) or {}
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrators only")


# ── Pages: login, first-time setup, logout, account, users ────────────────────
router = APIRouter()


@router.get("/login")
def login_page(request: Request, next: str = "/", error: str | None = None, info: str | None = None):
    if needs_setup():
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"next": _safe_next(next), "error": error, "info": info})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/")):
    try:
        r = httpx.post(f"{BACKEND_URL}/auth/login", json={"username": username, "password": password}, timeout=10)
    except httpx.HTTPError:
        return templates.TemplateResponse(request, "auth/login.html",
                                          {"next": _safe_next(next), "error": "The backend is not reachable."}, status_code=503)
    if r.status_code != 200:
        return templates.TemplateResponse(request, "auth/login.html",
                                          {"next": _safe_next(next), "error": "Wrong username or password.", "username": username},
                                          status_code=401)
    response = RedirectResponse(_safe_next(next), status_code=303)
    set_session_cookies(response, r.json(), request)
    return response


@router.get("/setup")
def setup_page(request: Request):
    if not needs_setup():
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "auth/setup.html", {})


@router.post("/setup")
def setup_submit(request: Request, username: str = Form(...), password: str = Form(...),
                 password2: str = Form(...), email: str = Form(""), first_name: str = Form(""), last_name: str = Form("")):
    if not needs_setup():
        return RedirectResponse("/login", status_code=303)
    error = None
    if password != password2:
        error = "The two passwords differ."
    else:
        r = httpx.post(f"{BACKEND_URL}/auth/setup",
                       json={"username": username, "password": password, "email": email or None,
                             "first_name": first_name, "last_name": last_name}, timeout=10)
        if r.status_code != 200:
            error = _error_text(r)
    if error:
        return templates.TemplateResponse(request, "auth/setup.html",
                                          {"error": error, "username": username, "email": email,
                                           "first_name": first_name, "last_name": last_name},
                                          status_code=400)
    response = RedirectResponse("/", status_code=303)
    set_session_cookies(response, r.json(), request)
    return response


@router.post("/logout")
def logout(request: Request):
    refresh = request.cookies.get(REFRESH_COOKIE)
    if refresh:
        try:
            httpx.post(f"{BACKEND_URL}/auth/logout", json={"refresh_token": refresh}, timeout=5)
        except httpx.HTTPError:
            pass
    response = RedirectResponse("/login?info=" + quote("You are logged out."), status_code=303)
    clear_session_cookies(response)
    return response


@router.get("/account")
def account_page(request: Request, error: str | None = None, info: str | None = None):
    return templates.TemplateResponse(request, "auth/account.html", {"error": error, "info": info})


@router.post("/account/name")
def account_name(request: Request, first_name: str = Form(""), last_name: str = Form("")):
    r = backend_api.patch(f"{BACKEND_URL}/auth/me", json={"first_name": first_name, "last_name": last_name}, timeout=10)
    if r.status_code != 200:
        return RedirectResponse("/account?error=" + quote(_error_text(r)), status_code=303)
    return RedirectResponse("/account?info=" + quote("Name saved."), status_code=303)


@router.post("/account/password")
def account_password(request: Request, current_password: str = Form(...), new_password: str = Form(...),
                     new_password2: str = Form(...)):
    if new_password != new_password2:
        return RedirectResponse("/account?error=" + quote("The two new passwords differ."), status_code=303)
    r = backend_api.post(f"{BACKEND_URL}/auth/password",
                         json={"current_password": current_password, "new_password": new_password}, timeout=10)
    if r.status_code != 204:
        return RedirectResponse("/account?error=" + quote(_error_text(r)), status_code=303)
    response = RedirectResponse("/login?info=" + quote("Password changed. Log in with the new password."), status_code=303)
    clear_session_cookies(response)
    return response


@router.get("/users")
def users_page(request: Request, error: str | None = None, info: str | None = None):
    require_admin(request)
    r = backend_api.get(f"{BACKEND_URL}/users/", timeout=5)
    users = r.json() if r.status_code == 200 else []
    return templates.TemplateResponse(request, "auth/users.html", {"users": users, "error": error, "info": info})


@router.post("/users/create")
def users_create(request: Request, username: str = Form(...), password: str = Form(...),
                 email: str = Form(""), is_admin: str = Form(""), first_name: str = Form(""), last_name: str = Form("")):
    require_admin(request)
    r = backend_api.post(f"{BACKEND_URL}/users/", timeout=10,
                         json={"username": username, "password": password, "email": email or None, "is_admin": bool(is_admin),
                               "first_name": first_name, "last_name": last_name})
    if r.status_code != 201:
        return RedirectResponse("/users?error=" + quote(_error_text(r)), status_code=303)
    return RedirectResponse("/users?info=" + quote(f"User '{username}' added."), status_code=303)


@router.post("/users/{uuid}/update")
def users_update(request: Request, uuid: str, is_active: str = Form(""), is_admin: str = Form(""), password: str = Form("")):
    require_admin(request)
    body = {}
    if is_active:
        body["is_active"] = is_active == "true"
    if is_admin:
        body["is_admin"] = is_admin == "true"
    if password:
        body["password"] = password
    r = backend_api.patch(f"{BACKEND_URL}/users/{uuid}", json=body, timeout=10)
    if r.status_code != 200:
        return RedirectResponse("/users?error=" + quote(_error_text(r)), status_code=303)
    return RedirectResponse("/users?info=" + quote(f"User '{r.json()['username']}' updated."), status_code=303)


def _error_text(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
    except Exception:
        return f"Request failed ({r.status_code})."
    if isinstance(detail, list):   # pydantic validation errors
        return "; ".join(f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
    return str(detail)
