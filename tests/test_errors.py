"""Tests for PreconditionError and pipeline error formatting."""

import os

import pytest

os.environ.setdefault("MONGODB_URI", "mongodb://localhost")

from google.genai.errors import ClientError, ServerError  # noqa: E402

from src.api.server import _format_pipeline_error  # noqa: E402
from src.errors import PreconditionError  # noqa: E402


def test_precondition_error_constructs():
    err = PreconditionError(
        capability="ingest_event_batch",
        context="event_metadata",
        missing={"outcome_type": "provide one of: upset_victory, extra_time_win, expected_win, draw"},
    )
    assert err.capability == "ingest_event_batch"
    assert err.context == "event_metadata"
    assert "outcome_type" in err.missing


def test_precondition_error_str_format():
    err = PreconditionError(
        capability="ingest_event_batch",
        context="event_metadata",
        missing={
            "name": "provide the match name",
            "outcome_type": "provide one of: upset_victory, extra_time_win, expected_win, draw",
        },
    )
    text = str(err)
    assert text.startswith("Cannot do ingest_event_batch for event_metadata:")
    assert "  - name (provide the match name)" in text
    assert "  - outcome_type (provide one of:" in text


# ---------------------------------------------------------------------------
# _format_pipeline_error — transient Gemini API error messages
# ---------------------------------------------------------------------------

def test_format_pipeline_error_503():
    msg = _format_pipeline_error(ServerError(503, {}, None))
    assert "temporarily unavailable" in msg
    assert "high demand" in msg


def test_format_pipeline_error_429():
    msg = _format_pipeline_error(ClientError(429, {}, None))
    assert "rate limit" in msg.lower()


def test_format_pipeline_error_5xx_generic():
    msg = _format_pipeline_error(ServerError(500, {}, None))
    assert "500" in msg
    assert "try again" in msg.lower()


def test_format_pipeline_error_4xx_generic():
    msg = _format_pipeline_error(ClientError(401, {}, None))
    assert "401" in msg
    assert "credentials" in msg.lower()


def test_format_pipeline_error_non_api_exception():
    msg = _format_pipeline_error(ValueError("unexpected failure"))
    assert "try again" in msg.lower()


# ---------------------------------------------------------------------------
# PreconditionError
# ---------------------------------------------------------------------------

def test_precondition_error_raisable_and_catchable():
    with pytest.raises(PreconditionError) as exc_info:
        raise PreconditionError(
            capability="test_cap",
            context="test_ctx",
            missing={"field": "fix it"},
        )
    caught = exc_info.value
    assert caught.capability == "test_cap"
    assert caught.context == "test_ctx"
    assert caught.missing == {"field": "fix it"}
    assert isinstance(caught, Exception)
