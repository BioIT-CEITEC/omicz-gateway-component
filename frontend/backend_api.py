"""
Calls from the frontend server to the backend API, with the logged-in user's access token.
The auth middleware sets the token for the request being served; calls to anything else
(e.g. GitHub for the version check) use httpx directly and never carry it.
"""
from contextvars import ContextVar

import httpx

access_token: ContextVar[str | None] = ContextVar("access_token", default=None)


def _headers(extra: dict | None) -> dict:
    headers = dict(extra or {})
    token = access_token.get()
    if token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# httpx is looked up at call time, so tests and the static demo can replace httpx.get & co.
def get(url, **kw):    return httpx.get(url, headers=_headers(kw.pop("headers", None)), **kw)
def post(url, **kw):   return httpx.post(url, headers=_headers(kw.pop("headers", None)), **kw)
def put(url, **kw):    return httpx.put(url, headers=_headers(kw.pop("headers", None)), **kw)
def patch(url, **kw):  return httpx.patch(url, headers=_headers(kw.pop("headers", None)), **kw)
def delete(url, **kw): return httpx.delete(url, headers=_headers(kw.pop("headers", None)), **kw)
