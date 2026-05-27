"""Tests for PreconditionError."""

import pytest

from src.errors import PreconditionError


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
