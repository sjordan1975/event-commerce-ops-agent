"""Tier-2 strategy-coherence eval for propose_review_queue (T-5.14).

Live strategic node — _FIXTURE_RESPONSE is NOT set. The propose_review_queue
LlmAgent node makes ~1 live Gemini call per run. Requires GOOGLE_API_KEY.

Run deliberately (pre-merge, local, nightly) — NOT on offline code-CI.
The gate is Tier-1 (test_step_5_trace.py, deterministic, no live queue calls).

Pass-rate gate: EVAL_REPEAT=20, >= 19/20 (95%, D-020).
Transient API errors (5xx / rate-limit / timeout) are retried once then excluded
from the denominator — so 95% measures judgment quality, not API uptime.

Assertions (T2-a through T2-f):
  (T2-a) every exploitation item's asset_id ∈ exploitation candidate set;
         every discovery item's ∈ discovery pool (no invent/cross-assign).
  (T2-b) exploitation non-empty (matched winners surfaced).
  (T2-c) discovery non-empty (worth-it candidate surfaced) — "surface meaningful work".
  (T2-d) identity-matched asset (ast-0, Messi) in exploitation, not dropped (D-026);
         soft: ranked 1 or 2 (tuning-flagged).
  (T2-e) every surfaced item has non-empty rationale; strategy_summary non-empty.
  (T2-f) queue_type matches half; ranks positive and distinct within each half.

Fixture shape (deliberately unambiguous — the lever for hitting 95%):
  ast-0: strong similarity (0.91, poster) + Messi identity match → exploitation leader
  ast-1: strong similarity (0.82, tshirt) + no identity → exploitation follow
  ast-2: weak similarity (0.31) + high emotional (0.92) + Messi candid → worth-it discovery
  ast-3: weak similarity (none) + low scores → not worth surfacing
"""

import math
import os
from datetime import datetime, timezone

import pytest
from google.genai import types

from src.models import ReviewQueue
from tests.evals.conftest import (
    _MockMCPClient,
    _collect_parts,
    build_runner_with_step5_mock,
    dump_trace,
    extract_tool_calls,
    extract_tool_responses,
    run_with_transient_retry,
    STEP5_EXPLOITATION_IDS,
    STEP5_DISCOVERY_IDS,
    _make_step5_assets_find_handler,
    _make_step5_vector_search_handler,
)

APP_NAME = "event_commerce_ops_agent"

_IDENTITY_ASSET = "ast-0"   # Messi identity match, must appear in exploitation
_WORTH_IT_DISCOVERY = "ast-2"  # High emotional + Messi candid, must appear in discovery

OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating France 3-2. "
    "Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, "
    "/tmp/wc-final/img03.jpg, /tmp/wc-final/img04.jpg. "
    "Match name: 'Argentina vs France'. Start: 2026-06-01T19:00:00Z. "
    "Process this batch."
)

# ---------------------------------------------------------------------------
# Seeded data (same as Tier-1 fixture)
# ---------------------------------------------------------------------------

_SEEDED_NARRATIVE = {
    "event_id": "evt-demo-1",
    "narrative_angle": "Messi crowns legendary career as Argentina defeats France on penalties",
    "key_figures": [
        {
            "name": "Lionel Messi",
            "team": "Argentina",
            "relevance": "Scored the decisive penalty in the shootout",
            "grounded_facts": ["2022 World Cup winner", "5th World Cup appearance"],
            "commercial_signal": "high",
        },
        {
            "name": "Kylian Mbappé",
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
]

_PERF_AGG_DOCS = [
    {"_id": "poster", "total_orders": 300, "total_impressions": 18000, "count": 6},
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


def _seed_mock(mock_client: _MockMCPClient) -> None:
    mock_client.register("find", "events", _make_events_find_handler())
    mock_client.register("find", "assets", _make_step5_assets_find_handler())
    mock_client.register("find", "player_context", _PLAYERS)
    mock_client.register("aggregate", "performance", _PERF_AGG_DOCS)
    mock_client.register_vector_search("assets", _make_step5_vector_search_handler())


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

async def _run_agent(runner) -> list:
    """Run agent, swallowing only the cosmetic OTel ValueError on generator exit.

    All other exceptions (including transient API errors from the live strategic
    node) propagate so that run_with_transient_retry can classify and retry them.
    The OTel 'Token was created in a different Context' ValueError is cosmetic and
    does not indicate a missing result (CLAUDE.md: do not attempt to fix it).
    """
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
    except ValueError as exc:
        # Cosmetic OTel warning on generator exit — ignore.
        if "Token was created in a different Context" not in str(exc):
            raise
    # All other exceptions propagate for run_with_transient_retry to handle.
    return events


# ---------------------------------------------------------------------------
# Assertion harness
# ---------------------------------------------------------------------------

def _check_single_run(events: list, mock_client, trace_label: str) -> list[str]:
    """Run strategy-coherence assertions. Returns list of failure strings (empty = pass)."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)
    tool_responses = extract_tool_responses(events)

    pipeline_responses = [r for r in tool_responses if r.get("name") == "run_event_pipeline"]
    review_queue_raw = None
    if pipeline_responses:
        resp = pipeline_responses[-1].get("response", {})
        result = resp.get("result", resp)
        review_queue_raw = result.get("review_queue")

    if review_queue_raw is None:
        failures.append(f"review_queue not in pipeline response. Trace: {trace_path}")
        return failures

    try:
        q = (
            ReviewQueue.model_validate_json(review_queue_raw)
            if isinstance(review_queue_raw, str)
            else ReviewQueue.model_validate(review_queue_raw)
        )
    except Exception as exc:
        failures.append(f"ReviewQueue parse failed: {exc}. Trace: {trace_path}")
        return failures

    expl_ids = [item.asset_id for item in q.exploitation]
    disc_ids = [item.asset_id for item in q.discovery]
    all_items = [*q.exploitation, *q.discovery]

    # (T2-a) membership: no cross-assign or invented asset_ids
    bad_expl = [aid for aid in expl_ids if aid not in STEP5_EXPLOITATION_IDS]
    bad_disc = [aid for aid in disc_ids if aid not in STEP5_DISCOVERY_IDS]
    if bad_expl:
        failures.append(
            f"(T2-a) exploitation contains out-of-pool ids: {bad_expl}. Trace: {trace_path}"
        )
    if bad_disc:
        failures.append(
            f"(T2-a) discovery contains out-of-pool ids: {bad_disc}. Trace: {trace_path}"
        )

    # (T2-b) exploitation non-empty
    if not q.exploitation:
        failures.append(f"(T2-b) exploitation is empty — matched winners not surfaced. Trace: {trace_path}")

    # (T2-c) discovery non-empty
    if not q.discovery:
        failures.append(f"(T2-c) discovery is empty — worth-it candidate not surfaced. Trace: {trace_path}")

    # (T2-d) identity-matched asset in exploitation (D-026); soft: ranked 1 or 2
    if _IDENTITY_ASSET not in expl_ids:
        failures.append(
            f"(T2-d) {_IDENTITY_ASSET} (Messi identity match) not in exploitation. Trace: {trace_path}"
        )
    else:
        idx = expl_ids.index(_IDENTITY_ASSET)
        if idx >= 2:
            failures.append(
                f"(T2-d) {_IDENTITY_ASSET} ranked position {idx+1} in exploitation "
                f"(soft gate: should be top 2). Trace: {trace_path}"
            )

    # (T2-e) non-empty rationale + strategy_summary
    for item in all_items:
        if not item.rationale.strip():
            failures.append(
                f"(T2-e) empty rationale on item {item.asset_id!r}. Trace: {trace_path}"
            )
    if not q.strategy_summary.strip():
        failures.append(f"(T2-e) strategy_summary is empty. Trace: {trace_path}")

    # (T2-f) queue_type matches half; ranks positive and distinct within each half
    for item in q.exploitation:
        if item.queue_type != "exploitation":
            failures.append(
                f"(T2-f) item {item.asset_id!r} in exploitation has queue_type={item.queue_type!r}. "
                f"Trace: {trace_path}"
            )
    for item in q.discovery:
        if item.queue_type != "discovery":
            failures.append(
                f"(T2-f) item {item.asset_id!r} in discovery has queue_type={item.queue_type!r}. "
                f"Trace: {trace_path}"
            )
    if len({i.rank for i in q.exploitation}) != len(q.exploitation):
        failures.append(f"(T2-f) duplicate ranks in exploitation. Trace: {trace_path}")
    if len({i.rank for i in q.discovery}) != len(q.discovery):
        failures.append(f"(T2-f) duplicate ranks in discovery. Trace: {trace_path}")
    for item in all_items:
        if item.rank < 1:
            failures.append(
                f"(T2-f) item {item.asset_id!r} has non-positive rank {item.rank}. Trace: {trace_path}"
            )

    return failures


# ---------------------------------------------------------------------------
# T-5.14: Tier-2 coherence eval (live, EVAL_REPEAT=20, ≥95%)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_5_strategy_coherence():
    """Strategy-coherence eval — live strategic node, 95%/20-run gate (D-020).

    Run deliberately: EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_5_coherence.py -v
    Requires GOOGLE_API_KEY. Transient API errors excluded from denominator.
    """
    n = int(os.environ.get("EVAL_REPEAT", "1"))
    passes = 0
    excluded = 0
    run_failures: list[tuple[int, list[str]]] = []

    for i in range(n):
        with build_runner_with_step5_mock(_SEEDED_NARRATIVE) as (runner, mock_client):
            _seed_mock(mock_client)

            # Use a closure that captures the current runner (loop-safe)
            _runner_ref = runner
            async def _run():
                return await _run_agent(_runner_ref)

            events, is_excluded = await run_with_transient_retry(_run)

        if is_excluded:
            excluded += 1
            continue

        label = f"step_5_coherence_run_{i}"
        failures = _check_single_run(events, mock_client, label)
        if not failures:
            passes += 1
        else:
            run_failures.append((i, failures))

    effective_n = n - excluded
    if effective_n == 0:
        pytest.skip(f"All {n} runs were excluded due to transient API errors.")

    required = math.ceil(effective_n * 0.95)
    if passes < required:
        report_lines = [
            f"Pass rate {passes}/{effective_n} ({100 * passes / effective_n:.0f}%) "
            f"below the 95% threshold ({required}/{effective_n} required). "
            f"({excluded} runs excluded for transient API errors.)",
            "",
            "Failed runs:",
        ]
        for run_idx, msgs in run_failures:
            report_lines.append(f"  Run {run_idx}:")
            for msg in msgs:
                report_lines.append(f"    - {msg}")
        assert False, "\n".join(report_lines)
