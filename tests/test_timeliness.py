"""Tests for compute_timeliness."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.timeliness import BASE_SCORES, compute_timeliness


def _kickoff_hours_ago(hours: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_timeliness():
    # 0h since kickoff → base score
    kickoff_now = _kickoff_hours_ago(0)
    for outcome_type, base in BASE_SCORES.items():
        result = compute_timeliness(outcome_type, kickoff_now)
        assert result["outcome_type"] == outcome_type
        assert math.isclose(result["timeliness"], base, rel_tol=1e-3)

    # 4h since kickoff → base / 2
    kickoff_4h = _kickoff_hours_ago(4)
    for outcome_type, base in BASE_SCORES.items():
        result = compute_timeliness(outcome_type, kickoff_4h)
        assert math.isclose(result["timeliness"], base / 2, rel_tol=1e-2)

    # 8h since kickoff → base / 4
    kickoff_8h = _kickoff_hours_ago(8)
    for outcome_type, base in BASE_SCORES.items():
        result = compute_timeliness(outcome_type, kickoff_8h)
        assert math.isclose(result["timeliness"], base / 4, rel_tol=1e-2)

    # Unknown outcome_type raises ValueError
    with pytest.raises(ValueError, match="Unknown outcome_type"):
        compute_timeliness("blowout", kickoff_now)

    # Returns dict with correct keys
    result = compute_timeliness("draw", kickoff_now)
    assert set(result.keys()) == {"timeliness", "outcome_type"}
    assert isinstance(result["timeliness"], float)

    # Accepts +00:00 suffix as well as Z
    kickoff_plus = _kickoff_hours_ago(0).replace("Z", "+00:00")
    result2 = compute_timeliness("draw", kickoff_plus)
    assert 0.0 <= result2["timeliness"] <= 1.0
