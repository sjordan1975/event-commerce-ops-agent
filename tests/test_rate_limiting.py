"""Tests for per-IP rate limiting on pipeline endpoints."""

import os

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

os.environ.setdefault("MONGODB_URI", "mongodb://localhost")

from src.api.server import app, limiter  # noqa: E402


# ---------------------------------------------------------------------------
# Lightweight probe route — "1/minute" so 429 fires on the 2nd request
# ---------------------------------------------------------------------------

@app.get("/test-rate-limit-probe")
@limiter.limit("1/minute")
async def _test_probe(request: Request):
    return {"ok": True}


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter._storage.reset()
    yield
    limiter._storage.reset()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_limiter_attached_to_app():
    assert hasattr(app.state, "limiter")
    assert app.state.limiter is limiter


def test_rate_limit_exceeded_handler_registered():
    assert RateLimitExceeded in dict(app.exception_handlers)


def test_limiter_enabled_by_default():
    assert limiter.enabled is True


# ---------------------------------------------------------------------------
# Mechanism — probe route confirms 429 fires end-to-end
# ---------------------------------------------------------------------------

def test_first_request_passes(client):
    resp = client.get("/test-rate-limit-probe")
    assert resp.status_code == 200


def test_second_request_returns_429(client):
    client.get("/test-rate-limit-probe")
    resp = client.get("/test-rate-limit-probe")
    assert resp.status_code == 429


def test_limit_resets_after_storage_clear(client):
    client.get("/test-rate-limit-probe")
    limiter._storage.reset()
    resp = client.get("/test-rate-limit-probe")
    assert resp.status_code == 200


def test_limiter_disabled_bypasses_limit(client):
    """limiter.enabled = False is the correct way to disable limits in tests."""
    limiter.enabled = False
    try:
        for _ in range(5):
            resp = client.get("/test-rate-limit-probe")
            assert resp.status_code == 200
    finally:
        limiter.enabled = True


# ---------------------------------------------------------------------------
# Non-pipeline endpoints are not rate-limited
# ---------------------------------------------------------------------------

def test_health_endpoint_not_rate_limited(client):
    for _ in range(15):
        resp = client.get("/health")
        assert resp.status_code != 429
