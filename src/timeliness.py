"""Timeliness calculator for event ingestion."""

from datetime import datetime, timezone

BASE_SCORES: dict[str, float] = {
    "upset_victory": 0.95,
    "extra_time_win": 0.85,
    "expected_win": 0.60,
    "draw": 0.40,
}


def compute_timeliness(outcome_type: str, kickoff_utc: str) -> dict:
    """Compute timeliness score for an event outcome.

    Returns {"timeliness": float, "outcome_type": str}.
    Formula: base_score × 0.5^(hours_since_kickoff / 4).
    """
    if outcome_type not in BASE_SCORES:
        raise ValueError(
            f"Unknown outcome_type: {outcome_type!r}. "
            f"Must be one of: {', '.join(BASE_SCORES)}"
        )
    kickoff = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    hours = max(0.0, (datetime.now(timezone.utc) - kickoff).total_seconds() / 3600)
    base = BASE_SCORES[outcome_type]
    timeliness = base * (0.5 ** (hours / 4))
    return {"timeliness": round(timeliness, 6), "outcome_type": outcome_type}
