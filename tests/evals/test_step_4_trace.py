"""Trace evals for the score_assets_with_vision capability.

T-4.13: Single-run outcome-shaped eval (8 assertions).
T-4.14: Pass-rate eval (≥95% over N runs, N defaults to 5 in CI, 20 for gate).

Scenario: Argentina vs France, same operator prompt as Steps 2/3.
3 ingested assets (all without scores), seeded narrative with Messi + Mbappé.
Vision helper patched via _default_vision_fixture_provider — detected_subjects
populated from key_figure_names, which satisfies the hallucination-guard assertion.

Assertions:
  (a) coordinator dispatched run_event_pipeline exactly once
  (b) mock client call sequence: ingest writes → context reads → context update
      → similarity reads/writes → scoring writes
  (c) exactly 3x update-many on assets with scores + detected_subjects + status in $set
  (d) scored_assets in session state (tool response) has 3 entries with valid structure
  (e) hallucination guard: every detected_subject is a substring of a key_figure name
  (f) distributional sanity: at least one asset has at least one score > 0.5
  (g) reasoning text present before tool call (CoT directive working)
  (h) on assertion failure, full trace dumped via dump_trace()
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
    extract_tool_responses,
)

APP_NAME = "event_commerce_ops_agent"

OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating France 3-2. "
    "Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, /tmp/wc-final/img03.jpg. "
    "Match name: 'Argentina vs France'. Start: 2026-06-01T19:00:00Z. "
    "Process this batch."
)

# Seeded key figures — names must be byte-identical with the vision mock output
_KEY_FIGURE_MESSI = "Lionel Messi"
_KEY_FIGURE_MBAPPE = "Kylian Mbappé"

# ---------------------------------------------------------------------------
# Seeded data
# ---------------------------------------------------------------------------

_SEEDED_NARRATIVE = {
    "event_id": "evt-demo-1",
    "narrative_angle": "Messi crowns legendary career as Argentina defeats France on penalties",
    "key_figures": [
        {
            "name": _KEY_FIGURE_MESSI,
            "team": "Argentina",
            "relevance": "Scored the decisive penalty in the shootout",
            "grounded_facts": ["2022 World Cup winner", "5th World Cup appearance"],
            "commercial_signal": "high",
        },
        {
            "name": _KEY_FIGURE_MBAPPE,
            "team": "France",
            "relevance": "Hat-trick in the final",
            "grounded_facts": ["2018 World Cup winner", "Youngest scorer in WC final"],
            "commercial_signal": "high",
        },
    ],
    "commercial_timing": "Aggressive — timeliness 0.87, ~6h window remaining",
    "historical_baseline": {
        "outcome_type": "upset_victory",
        "past_event_count": 3,
        "top_product_route": "poster",
        "total_orders": 450,
        "total_impressions": 22000,
        "notes": "3 past upsets; poster routes dominated conversion",
    },
}

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
    "event_narrative": _SEEDED_NARRATIVE,
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
        "notable_facts": ["5th World Cup appearance", "2022 World Cup winner"],
        "career_milestones": "Widely regarded as final World Cup; 2022 champion",
        "commercial_signal": "high",
    },
    {
        "player_id": "player-mbappe",
        "name": "Kylian Mbappe",
        "nationality": "French",
        "team": "France",
        "position": "Forward",
        "notable_facts": ["Hat-trick in the 2022 World Cup final", "2018 World Cup winner"],
        "career_milestones": "France's all-time top scorer; 2018 champion",
        "commercial_signal": "high",
    },
]

_PERF_AGG_DOCS = [
    {"_id": "poster", "total_orders": 300, "total_impressions": 18000, "count": 6},
    {"_id": "tshirt", "total_orders": 120, "total_impressions": 7000, "count": 4},
]

_VECTOR_SEARCH_NEIGHBORS = [
    {
        "asset_id": f"past-asset-{j}",
        "event_id": "evt-past-1",
        "similarity": 0.85 - j * 0.05,
        "product_route": "poster",
        "scores": None,
    }
    for j in range(5)
]


def _make_events_find_handler():
    def handler(args: dict) -> list:
        f = args.get("filter", {})
        event_id_filter = f.get("event_id")
        outcome_filter = f.get("outcome_type")

        if isinstance(event_id_filter, str):
            return [{**_SEEDED_EVENT, "event_id": event_id_filter}]

        if outcome_filter is not None and isinstance(event_id_filter, dict) and "$ne" in event_id_filter:
            exclude = event_id_filter["$ne"]
            return [
                e for e in _PAST_EVENTS
                if e["outcome_type"] == outcome_filter and e["event_id"] != exclude
            ]

        return []

    return handler


def _make_assets_find_handler():
    def handler(args: dict) -> list:
        f = args.get("filter", {})
        if "event_id" in f and "status" not in f:
            event_id = f["event_id"]
            return [
                {
                    "asset_id": f"ast-{i}",
                    "event_id": event_id,
                    "content_url": f"/tmp/wc-final/img0{i + 1}.jpg",
                    "status": "ingested",
                    "upload_date": datetime.now(timezone.utc).isoformat(),
                    "product_route": None,
                    "queue_type": None,
                    "embedding": None,
                    "scores": None,
                    "detected_subjects": None,
                    "campaign_id": None,
                    "similar_assets": None,
                }
                for i in range(3)
            ]
        return []

    return handler


def _make_vector_search_handler():
    _call_count = {"n": 0}

    def handler(args: dict) -> list:
        _call_count["n"] += 1
        if _call_count["n"] >= 3:
            return []
        return _VECTOR_SEARCH_NEIGHBORS

    return handler


def _seed_mock(mock_client) -> None:
    mock_client.register("find", "events", _make_events_find_handler())
    mock_client.register("find", "assets", _make_assets_find_handler())
    mock_client.register("find", "player_context", _PLAYERS)
    mock_client.register("aggregate", "performance", _PERF_AGG_DOCS)
    mock_client.register_vector_search("assets", _make_vector_search_handler())


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

def _assert_single_run(
    events: list,
    mock_client,
    trace_label: str,
    vision_call_count: int,
) -> list[str]:
    """Run all assertions. Returns list of failure messages (empty = pass)."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)
    all_parts = _collect_parts(events)
    tool_calls = extract_tool_calls(events)
    tool_responses = extract_tool_responses(events)

    pipeline_calls = [c for c in tool_calls if c["name"] == "run_event_pipeline"]

    # (a) coordinator dispatched run_event_pipeline exactly once
    if len(pipeline_calls) != 1:
        failures.append(
            f"(a) Expected run_event_pipeline called 1 time, got {len(pipeline_calls)}. "
            f"Trace: {trace_path}"
        )

    # (b) call sequence: ingest writes before context reads before similarity writes before scoring writes
    call_log = mock_client.calls
    ingest_insert_idx = next(
        (i for i, (tn, a) in enumerate(call_log)
         if tn == "insert-many" and a.get("collection") == "assets"),
        None,
    )
    context_event_read_idx = next(
        (i for i, (tn, a) in enumerate(call_log)
         if tn == "find" and a.get("collection") == "events"
         and isinstance(a.get("filter", {}).get("event_id"), str)),
        None,
    )
    first_embedding_update_idx = next(
        (i for i, (tn, a) in enumerate(call_log)
         if tn == "update-many" and a.get("collection") == "assets"
         and "embedding" in a.get("update", {}).get("$set", {})),
        None,
    )
    first_scoring_write_idx = next(
        (i for i, (tn, a) in enumerate(call_log)
         if tn == "update-many" and a.get("collection") == "assets"
         and "scores" in a.get("update", {}).get("$set", {})),
        None,
    )
    if ingest_insert_idx is None:
        failures.append(f"(b) No insert-many on assets recorded. Trace: {trace_path}")
    elif context_event_read_idx is None:
        failures.append(f"(b) No find on events by event_id recorded. Trace: {trace_path}")
    elif first_embedding_update_idx is None:
        failures.append(f"(b) No embedding update-many recorded. Trace: {trace_path}")
    elif first_scoring_write_idx is None:
        failures.append(f"(b) No scoring update-many recorded. Trace: {trace_path}")
    elif not (ingest_insert_idx < context_event_read_idx < first_embedding_update_idx < first_scoring_write_idx):
        failures.append(
            f"(b) Call order wrong: ingest={ingest_insert_idx}, context_read={context_event_read_idx}, "
            f"first_embedding={first_embedding_update_idx}, first_scoring={first_scoring_write_idx}. "
            f"Expected ingest < context < similarity < scoring. Trace: {trace_path}"
        )

    # (c) exactly 3x update-many on assets with scores + detected_subjects + status
    scoring_writes = [
        (tn, a) for tn, a in call_log
        if tn == "update-many" and a.get("collection") == "assets"
        and "scores" in a.get("update", {}).get("$set", {})
        and "detected_subjects" in a.get("update", {}).get("$set", {})
        and "status" in a.get("update", {}).get("$set", {})
    ]
    if len(scoring_writes) != 3:
        failures.append(
            f"(c) Expected 3 scoring update-many calls, got {len(scoring_writes)}. "
            f"Trace: {trace_path}"
        )
    for _, sw_args in scoring_writes:
        set_block = sw_args["update"]["$set"]
        if set_block.get("status") != "scored":
            failures.append(
                f"(c) Scoring write status != 'scored': got {set_block.get('status')!r}. "
                f"Trace: {trace_path}"
            )
            break

    # (d) scored_assets in tool response has 3 entries with valid structure
    pipeline_responses = [r for r in tool_responses if r.get("name") == "run_event_pipeline"]
    scored_entries = []
    if pipeline_responses:
        resp = pipeline_responses[-1].get("response", {})
        result = resp.get("result", resp)
        scored_entries = result.get("scored_assets") or []
    if len(scored_entries) != 3:
        failures.append(
            f"(d) scored_assets in tool response: expected 3 entries, got {len(scored_entries)}. "
            f"Trace: {trace_path}"
        )
    for entry in scored_entries:
        if not isinstance(entry.get("scores"), dict):
            failures.append(
                f"(d) scored entry 'scores' is not a dict: {entry!r}. Trace: {trace_path}"
            )
            break
        scores = entry["scores"]
        for dim in ("quality_score", "merch_score", "emotional_score", "social_score", "identity_score"):
            val = scores.get(dim)
            if val is None or not (0.0 <= val <= 1.0):
                failures.append(
                    f"(d) scores.{dim}={val!r} out of [0,1]. Trace: {trace_path}"
                )
                break
        if not isinstance(entry.get("detected_subjects"), list):
            failures.append(
                f"(d) detected_subjects is not a list: {entry!r}. Trace: {trace_path}"
            )
            break

    # (e) hallucination guard: every detected_subject is a substring of a key_figure name
    key_figure_names = [_KEY_FIGURE_MESSI, _KEY_FIGURE_MBAPPE]
    for entry in scored_entries:
        for subject in entry.get("detected_subjects", []):
            if not any(subject in kf_name for kf_name in key_figure_names):
                failures.append(
                    f"(e) Hallucinated subject {subject!r} not a substring of any key_figure name "
                    f"{key_figure_names}. Trace: {trace_path}"
                )

    # (f) distributional sanity: at least one asset has at least one score > 0.5
    has_nonzero = any(
        any(
            entry.get("scores", {}).get(dim, 0.0) > 0.5
            for dim in ("quality_score", "merch_score", "emotional_score", "social_score", "identity_score")
        )
        for entry in scored_entries
    )
    if scored_entries and not has_nonzero:
        failures.append(
            f"(f) Distributional sanity failed: no asset has any score > 0.5 — "
            f"possible all-zeros regression. Trace: {trace_path}"
        )

    # (g) reasoning text present before the first tool call (CoT directive)
    first_tool_idx = next(
        (i for i, p in enumerate(all_parts) if p["kind"] == "tool_call"), None
    )
    text_before_tool = any(
        p["kind"] == "text" and i < (first_tool_idx if first_tool_idx is not None else len(all_parts))
        for i, p in enumerate(all_parts)
    )
    if not text_before_tool:
        failures.append(
            f"(g) No reasoning text before tool call — CoT directive not firing. "
            f"Trace: {trace_path}"
        )

    return failures


# ---------------------------------------------------------------------------
# T-4.13: Single-run eval
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_4_single_run():
    """Single-run outcome-shaped trace eval for score_assets_with_vision."""
    import src.capabilities.scoring as scoring_module

    with build_runner_with_mock_db() as (runner, mock_client):
        _seed_mock(mock_client)
        events = await _run_agent(runner)
        vision_call_count = scoring_module._score_asset_with_vision.call_count

    failures = _assert_single_run(events, mock_client, "step_4_single_run", vision_call_count)
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# T-4.14: Pass-rate eval (N=20, ≥95% threshold)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_4_pass_rate():
    """Pass-rate eval: ≥95% of N runs must satisfy all assertions (D-020)."""
    n = int(os.environ.get("EVAL_REPEAT", "5"))
    passes = 0
    run_failures: list[tuple[int, list[str]]] = []

    for i in range(n):
        import src.capabilities.scoring as scoring_module

        with build_runner_with_mock_db() as (runner, mock_client):
            _seed_mock(mock_client)
            events = await _run_agent(runner)
            vision_call_count = scoring_module._score_asset_with_vision.call_count

        failures = _assert_single_run(events, mock_client, f"step_4_pass_rate_run_{i}", vision_call_count)
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
