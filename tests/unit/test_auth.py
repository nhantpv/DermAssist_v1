"""Unit tests for backend.auth (TIP-005-CANONICAL-V1)."""
import jwt
import pytest

from backend.auth import (
    create_access_token,
    decode_access_token,
    verify_password,
)

# The bcrypt hash of "demo" from migrations/002_seed_demo_user.sql.
# Pinned here so we catch any drift between code expectations and the
# seeded demo account.
DEMO_HASH = "$2b$12$HZXsGd866KPOaND78MWFz.w3yPUPUHOSblPjU69MjSJa3.FEpPIwG"


# === verify_password ===

def test_verify_password_accepts_correct_password():
    assert verify_password("demo", DEMO_HASH) is True


def test_verify_password_rejects_wrong_password():
    assert verify_password("wrong", DEMO_HASH) is False


def test_verify_password_rejects_empty_password():
    assert verify_password("", DEMO_HASH) is False


def test_verify_password_handles_garbage_hash_gracefully():
    """A malformed hash should return False, not raise."""
    assert verify_password("demo", "not-a-real-bcrypt-hash") is False


# === JWT round-trip ===

def test_jwt_round_trip():
    """Token encoded then decoded yields the same sub + role."""
    token = create_access_token(sub="demo", role="demo")
    payload = decode_access_token(token)
    assert payload["sub"] == "demo"
    assert payload["role"] == "demo"
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_decode_rejects_garbage():
    """Garbage token raises a PyJWTError subclass."""
    with pytest.raises(jwt.PyJWTError):
        decode_access_token("garbage.not.a.token")


def test_jwt_decode_rejects_tampered_signature():
    """A token signed with a different key fails verification."""
    forged = jwt.encode(
        {"sub": "evil", "role": "admin"}, "different_secret_key", algorithm="HS256"
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)
