"""
Passwords, access tokens and refresh tokens.

Access token: a JWT (HS256) valid for ACCESS_TOKEN_TTL, signed with a key from JWT_SECRET or,
if that is not set, a random key stored once in the app_secrets table (so tokens survive restarts
and no setting is required). Signed and checked with the standard library: no extra package, so
an update from the web interface works without rebuilding the images.

Refresh token: a random string valid for REFRESH_TOKEN_TTL; only its SHA-256 is stored.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import timedelta

import bcrypt

ACCESS_TOKEN_TTL  = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)
MIN_PASSWORD_LENGTH = 8

_signing_key: bytes | None = None


class InvalidToken(Exception):
    pass


# ── Passwords ─────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# a real hash to compare against when the user does not exist, so a wrong username takes as long as a wrong password
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password_or_dummy(password: str, hashed: str | None) -> bool:
    if hashed is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, hashed)


# ── Signing key ───────────────────────────────────────────────────────────────
def signing_key() -> bytes:
    """JWT_SECRET if set; otherwise a key generated once and kept in app_secrets."""
    global _signing_key
    if _signing_key is None:
        env = os.getenv("JWT_SECRET")
        if env:
            _signing_key = env.encode()
        else:
            from db.session import SESSION_LOCAL
            from db.models.app_secrets import AppSecrets
            db = SESSION_LOCAL()
            try:
                row = db.get(AppSecrets, "jwt_signing_key")
                if row is None:
                    row = AppSecrets(key="jwt_signing_key", value=secrets.token_urlsafe(48))
                    db.add(row)
                    db.commit()
                _signing_key = row.value.encode()
            finally:
                db.close()
    return _signing_key


# ── Access tokens (JWT, HS256) ────────────────────────────────────────────────
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_access_token(user_uuid: str, username: str, is_admin: bool, key: bytes | None = None, now: float | None = None) -> str:
    now = int(now if now is not None else time.time())
    header  = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_uuid), "name": username, "adm": bool(is_admin), "typ": "access",
               "iat": now, "exp": now + int(ACCESS_TOKEN_TTL.total_seconds())}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(key or signing_key(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def decode_access_token(token: str, key: bytes | None = None, now: float | None = None) -> dict:
    """The token's claims; raises InvalidToken if it is malformed, not ours, not an access token, or expired."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_unb64(header_b64))
        if header.get("alg") != "HS256":
            raise InvalidToken("unexpected algorithm")
        expected = hmac.new(key or signing_key(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature_b64)):
            raise InvalidToken("bad signature")
        payload = json.loads(_unb64(payload_b64))
    except InvalidToken:
        raise
    except Exception as e:
        raise InvalidToken(f"malformed token: {e}")
    if payload.get("typ") != "access":
        raise InvalidToken("not an access token")
    if int(payload.get("exp", 0)) <= int(now if now is not None else time.time()):
        raise InvalidToken("expired")
    return payload


# ── Refresh tokens ────────────────────────────────────────────────────────────
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
