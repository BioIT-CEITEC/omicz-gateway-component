"""Access tokens (HS256 JWT signed with the standard library), passwords and refresh-token hashing."""
import base64
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import security
from core.security import (create_access_token, decode_access_token, InvalidToken, hash_password,
                           verify_password, verify_password_or_dummy, hash_token, new_refresh_token, ACCESS_TOKEN_TTL)

KEY = b"test-key"


def test_round_trip():
    t = create_access_token("u-1", "alice", True, key=KEY)
    claims = decode_access_token(t, key=KEY)
    assert claims["sub"] == "u-1" and claims["name"] == "alice" and claims["adm"] is True and claims["typ"] == "access"


def test_expires_after_the_ttl():
    now = time.time()
    t = create_access_token("u-1", "alice", False, key=KEY, now=now)
    decode_access_token(t, key=KEY, now=now + ACCESS_TOKEN_TTL.total_seconds() - 1)
    with pytest.raises(InvalidToken, match="expired"):
        decode_access_token(t, key=KEY, now=now + ACCESS_TOKEN_TTL.total_seconds())


def test_other_key_is_rejected():
    with pytest.raises(InvalidToken, match="signature"):
        decode_access_token(create_access_token("u-1", "alice", False, key=KEY), key=b"other")


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def test_changed_claims_are_rejected():
    head, body, sig = create_access_token("u-1", "alice", False, key=KEY).split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    claims["adm"] = True                                   # try to become an administrator
    with pytest.raises(InvalidToken, match="signature"):
        decode_access_token(f"{head}.{_b64(claims)}.{sig}", key=KEY)


def test_alg_none_is_rejected():
    _, body, _ = create_access_token("u-1", "alice", True, key=KEY).split(".")
    with pytest.raises(InvalidToken, match="algorithm"):
        decode_access_token(f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{body}.", key=KEY)


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c.d", "!!.!!.!!"])
def test_garbage_is_rejected(token):
    with pytest.raises(InvalidToken):
        decode_access_token(token, key=KEY)


def test_signing_key_comes_from_jwt_secret(monkeypatch):
    monkeypatch.setattr(security, "_signing_key", None)
    monkeypatch.setenv("JWT_SECRET", "from-env")
    assert security.signing_key() == b"from-env"
    monkeypatch.setattr(security, "_signing_key", None)


def test_passwords():
    h = hash_password("correct horse")
    assert h != "correct horse"
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-bcrypt-hash")
    assert not verify_password_or_dummy("anything", None)   # unknown user: compared against a dummy hash


def test_refresh_tokens_are_random_and_stored_hashed():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 60
    assert hash_token(a) == hash_token(a) and hash_token(a) != a and len(hash_token(a)) == 64
