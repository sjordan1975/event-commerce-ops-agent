"""Trace evals for the build_event_context capability.

T-2.15: Single-run outcome-shaped eval (9 assertions).
T-2.16: Pass-rate eval (≥95% over N runs, N defaults to 5 in CI, 20 for gate).

Scenario: Argentina vs France, event_id="evt-demo-1", outcome_type="upset_victory".
Player context seeded for both teams. 3 past events of the same outcome_type with
performance aggregate data. Operator prompt: "The event with id evt-demo-1 has been
ingested. Build context for it."

The agent must:
  (a) call build_event_context exactly once
  (b) NOT call ingest_event_batch (event already ingested per prompt)
  (c) pass event_id="evt-demo-1" as the argument
  (d) drive all four MongoDB reads (events find by id, events find by outcome_type,
      performance aggregate, player_context find by team)
  (e) drive update-many on events with event_narrative populated (per D-022)
  (f) return dict with four EventNarrative top-level keys
  (g) grounded_facts for each key_figure are literal substrings of that player's
      notable_facts (hallucination guard)
  (h) reasoning text present before the tool call (CoT directive)
  (i) commercial_signal for each key_figure matches the seeded player_context value
      exactly (prompt instructs "copy commercial_signal as-is"; any paraphrase = violation)
"""

import math
import os
from datetime import datetime, timezone

import pytest
from google.genai import types

from tests.evals.conftest import (
    _collect_parts,
    build_runner_with_mock_db,
    dump_trace,
    extract_tool_calls,
)

APP_NAME = "event_commerce_ops_agent"

OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating France 3-2. "
    "Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, /tmp/wc-final/img03.jpg. "
    "Match name: 'Argentina vs France'. Start: 2026-06-01T19:00:00Z. "
    "Process this batch."
)

# ---------------------------------------------------------------------------
# Seeded data
# ---------------------------------------------------------------------------

_SEEDED_EVENT = {
    "event_id": "evt-demo-1",
    "name": "Argentina vs France",
    "home_team": "Argentina",
    "away_team": "France",
    "location": "Lusail Stadium, Qatar",
    "start_date": "2026-06-01T19:00:00Z",
    "final_score": "3-2",
    "outcome_type": "upset_victory",
    "timeliness": 0.87,
    "ingested_at": datetime.now(timezone.utc).isoformat(),
    "event_narrative": None,
}

_PAST_EVENTS = [
    {
        "event_id": f"evt-past-{i}",
        "name": f"Past Upset {i}",
        "home_team": "Underdog",
        "away_team": "Favorite",
        "location": "Stadium",
        "start_date": "2024-01-01T15:00:00Z",
        "final_score": "1-0",
        "outcome_type": "upset_victory",
        "timeliness": 0.9,
        "ingested_at": "2024-01-01T17:00:00Z",
        "event_narrative": None,
    }
    for i in range(1, 4)
]

_PLAYERS = [
    {
        "player_id": "player-messi",
        "name": "Lionel Messi",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Forward",
        "notable_facts": [
            "5th World Cup appearance",
            "2022 World Cup winner",
            "All-time leading scorer in World Cup finals",
        ],
        "career_milestones": "Widely regarded as final World Cup; 2022 champion",
        "commercial_signal": "high",
    },
    {
        "player_id": "player-mbappe",
        "name": "Kylian Mbappe",
        "nationality": "French",
        "team": "France",
        "position": "Forward",
        "notable_facts": [
            "Youngest French player to score in a World Cup final",
            "Hat-trick in the 2022 World Cup final",
            "2018 World Cup winner",
        ],
        "career_milestones": "France's all-time top scorer; 2018 champion",
        "commercial_signal": "high",
    },
    {
        "player_id": "player-di-maria",
        "name": "Angel Di Maria",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Winger",
        "notable_facts": [
            "Scored the opening goal in the 2022 World Cup final",
            "Copa America winner 2021",
        ],
        "career_milestones": "Key playmaker for Argentina across three World Cups",
        "commercial_signal": "medium",
    },
]

# Aggregate docs sorted by total_orders desc (poster first)
_PERF_AGG_DOCS = [
    {"_id": "poster", "total_orders": 300, "total_impressions": 18000, "count": 6},
    {"_id": "tshirt", "total_orders": 120, "total_impressions": 7000, "count": 4},
]

# Map of notable_facts by player name for hallucination guard
_PLAYER_FACTS_BY_NAME: dict[str, list[str]] = {
    p["name"]: p["notable_facts"] for p in _PLAYERS
}

# Map of commercial_signal by player name for fidelity guard (assertion i)
_PLAYER_SIGNAL_BY_NAME: dict[str, str] = {
    p["name"]: p["commercial_signal"] for p in _PLAYERS
}


def _make_events_find_handler():
    """Dispatch find on events based on filter shape.

    Under D-024 the event_id is dynamic (a fresh uuid per run, generated by the
    ingest node), so the get_event branch synthesizes a matching event document
    using whichever event_id the workflow asks for.
    """
    def handler(args: dict) -> list:
        f = args.get("filter", {})
        event_id_filter = f.get("event_id")
        outcome_filter = f.get("outcome_type")

        if isinstance(event_id_filter, str):
            # get_event: return seeded event but with the dynamic event_id
            return [{**_SEEDED_EVENT, "event_id": event_id_filter}]

        if outcome_filter is not None and isinstance(event_id_filter, dict) and "$ne" in event_id_filter:
            # find_past_events_by_outcome: filter by outcome_type, exclude this event
            exclude = event_id_filter["$ne"]
            return [
                e for e in _PAST_EVENTS
                if e["outcome_type"] == outcome_filter and e["event_id"] != exclude
            ]

        return []

    return handler


def _seed_mock(mock_client) -> None:
    """Register all seeded reads on the mock client."""
    mock_client.register("find", "events", _make_events_find_handler())
    mock_client.register("find", "player_context", _PLAYERS)
    mock_client.register("aggregate", "performance", _PERF_AGG_DOCS)


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

async def _run_agent(runner) -> list:
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id="eval_user"
    )
    msg = types.Content(
        role="user",
        parts=[types.Part(text=OPERATOR_PROMPT)],
    )
    events = []
    try:
        async for event in runner.run_async(
            user_id="eval_user",
            session_id=session.id,
            new_message=msg,
        ):
            events.append(event)
    except (ValueError, Exception):
        pass
    return events


# ---------------------------------------------------------------------------
# Assertion harness
# ---------------------------------------------------------------------------

def _assert_single_run(events: list, mock_client, trace_label: str) -> list[str]:
    """Run all eight assertions. Returns list of failure messages (empty = pass)."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)
    all_parts = _collect_parts(events)
    tool_calls = extract_tool_calls(events)

    pipeline_calls = [c for c in tool_calls if c["name"] == "run_event_pipeline"]

    # (a) coordinator dispatched the pipeline exactly once (D-024: workflow runs
    # ingest + context as one graph; context-specific behavior is verified
    # downstream via the MongoDB-call assertions).
    if len(pipeline_calls) != 1:
        failures.append(
            f"(a) Expected run_event_pipeline called 1 time, got {len(pipeline_calls)}. "
            f"Trace: {trace_path}"
        )

    # (b) coordinator extracted outcome_type=upset_victory from the operator's
    # message — load-bearing for downstream context cohort lookup.
    if pipeline_calls:
        meta = pipeline_calls[0]["args"].get("event_metadata", {})
        if meta.get("outcome_type") != "upset_victory":
            failures.append(
                f"(b) outcome_type in event_metadata: expected 'upset_victory', "
                f"got {meta.get('outcome_type')!r}. Trace: {trace_path}"
            )

    # (d) all four MongoDB reads recorded
    find_events_by_id = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "find" and a.get("collection") == "events"
        and isinstance(a.get("filter", {}).get("event_id"), str)
    ]
    find_events_by_outcome = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "find" and a.get("collection") == "events"
        and isinstance(a.get("filter", {}).get("event_id"), dict)
    ]
    agg_calls = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "aggregate" and a.get("collection") == "performance"
    ]
    find_players = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "find" and a.get("collection") == "player_context"
    ]

    if not find_events_by_id:
        failures.append(f"(d) Missing find on events by event_id. Trace: {trace_path}")
    if not find_events_by_outcome:
        failures.append(f"(d) Missing find on events by outcome_type. Trace: {trace_path}")
    if not agg_calls:
        failures.append(f"(d) Missing aggregate on performance. Trace: {trace_path}")
    if not find_players:
        failures.append(f"(d) Missing find on player_context. Trace: {trace_path}")

    # (e) update-many on events with event_narrative
    update_calls = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "update-many" and a.get("collection") == "events"
        and "event_narrative" in a.get("update", {}).get("$set", {})
    ]
    if not update_calls:
        failures.append(
            f"(e) Missing update-many on events with event_narrative. Trace: {trace_path}"
        )

    # (f) return dict has four EventNarrative top-level keys
    narrative_dict = None
    if update_calls:
        narrative_dict = update_calls[0][1]["update"]["$set"]["event_narrative"]

    if narrative_dict is not None:
        required_keys = {"event_id", "narrative_angle", "key_figures", "commercial_timing", "historical_baseline"}
        missing_keys = required_keys - set(narrative_dict.keys())
        if missing_keys:
            failures.append(
                f"(f) Narrative missing keys: {missing_keys}. Trace: {trace_path}"
            )
    elif not update_calls:
        failures.append(f"(f) Cannot check return shape — update-many not called. Trace: {trace_path}")

    # (g) hallucination guard: grounded_facts are substrings of player notable_facts
    if narrative_dict:
        key_figures = narrative_dict.get("key_figures", [])
        for kf in key_figures:
            kf_name = kf.get("name", "")
            grounded_facts = kf.get("grounded_facts", [])
            known_facts = _PLAYER_FACTS_BY_NAME.get(kf_name)
            if known_facts is None:
                failures.append(
                    f"(g) key_figure '{kf_name}' not in seeded player_context — "
                    f"possible hallucinated player. Trace: {trace_path}"
                )
                continue
            for gf in grounded_facts:
                if not any(gf in nf for nf in known_facts):
                    failures.append(
                        f"(g) Hallucinated fact for '{kf_name}': {gf!r} is not a "
                        f"substring of any notable_fact. "
                        f"Known facts: {known_facts}. Trace: {trace_path}"
                    )

    # (i) commercial_signal fidelity: must match seeded player_context value exactly
    if narrative_dict:
        key_figures = narrative_dict.get("key_figures", [])
        for kf in key_figures:
            kf_name = kf.get("name", "")
            kf_signal = kf.get("commercial_signal", "")
            expected_signal = _PLAYER_SIGNAL_BY_NAME.get(kf_name)
            if expected_signal is None:
                continue  # hallucinated player already caught by (g)
            if kf_signal != expected_signal:
                failures.append(
                    f"(i) commercial_signal mismatch for '{kf_name}': "
                    f"expected {expected_signal!r}, got {kf_signal!r}. Trace: {trace_path}"
                )

    # (h) reasoning text appears before the tool call
    first_tool_idx = next(
        (i for i, p in enumerate(all_parts) if p["kind"] == "tool_call"), None
    )
    text_before_tool = any(
        p["kind"] == "text" and i < (first_tool_idx if first_tool_idx is not None else len(all_parts))
        for i, p in enumerate(all_parts)
    )
    if not text_before_tool:
        failures.append(
            f"(h) No reasoning text before tool call — CoT directive not firing. "
            f"Trace: {trace_path}"
        )

    return failures


# ---------------------------------------------------------------------------
# T-2.15: Single-run eval
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_2_single_run():
    """Single-run outcome-shaped trace eval for build_event_context."""
    with build_runner_with_mock_db() as (runner, mock_client):
        _seed_mock(mock_client)
        events = await _run_agent(runner)

    failures = _assert_single_run(events, mock_client, "step_2_single_run")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# T-2.16: Pass-rate eval (N=20, ≥95% threshold)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_2_pass_rate():
    """Pass-rate eval: ≥95% of N runs must satisfy all eight assertions (D-020)."""
    n = int(os.environ.get("EVAL_REPEAT", "5"))
    passes = 0
    run_failures: list[tuple[int, list[str]]] = []

    for i in range(n):
        with build_runner_with_mock_db() as (runner, mock_client):
            _seed_mock(mock_client)
            events = await _run_agent(runner)
        failures = _assert_single_run(events, mock_client, f"step_2_pass_rate_run_{i}")
        if not failures:
            passes += 1
        else:
            run_failures.append((i, failures))

    required = math.ceil(n * 0.95)
    if passes < required:
        report_lines = [
            f"Pass rate {passes}/{n} ({100 * passes / n:.0f}%) below the 95% threshold "
            f"({required}/{n} required).",
            "",
            "Failed runs:",
        ]
        for run_idx, msgs in run_failures:
            report_lines.append(f"  Run {run_idx}:")
            for msg in msgs:
                report_lines.append(f"    - {msg}")
        assert False, "\n".join(report_lines)
