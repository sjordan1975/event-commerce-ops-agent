"""Tier-1 plumbing eval for propose_review_queue (T-5.13).

Deterministic — _FIXTURE_RESPONSE is set, so the strategic LlmAgent node uses a
canned ReviewQueue and makes zero live calls to the queue model. The coordinator
LlmAgent still runs live (consistent with Steps 2-4; requires GOOGLE_API_KEY).

Assertions (T1-a through T1-e):
  (T1-a) ReviewQueue parses from state["review_queue"] via ADK output_key.
  (T1-b) prepare_queue_candidates split correct: ast-0/ast-1 in exploitation pool,
         ast-2/ast-3 in discovery pool; inferred_route carried for exploitation.
  (T1-c) persist_review_queue issued save_queue_assignment per surfaced item:
         exploitation route = mechanical inferred_route (not LLM's); discovery route
         = canned LLM route; ast-1 (unsurfaced exploitation) gets no write.
         ast-3 (cross-assigned) triggers membership_violation.
  (T1-d) Cross-assigned item (ast-3) recorded in membership_violations, no crash.
  (T1-e) Coordinator dispatched run_event_pipeline exactly once; reasoning text
         present pre-dispatch.

Note on "offline / no GOOGLE_API_KEY": T-5.13 in the task list claims "offline,
no GOOGLE_API_KEY needed," but the coordinator LlmAgent runs live (consistent with
Steps 2-4). The claim means the NEW live call (strategic node) is mocked — the
coordinator call is unchanged from prior steps. This is the gate main stays green
against.
"""

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
    step5_fixture_response,
    STEP5_EXPLOITATION_IDS,
    STEP5_DISCOVERY_IDS,
    _STEP5_INFERRED_ROUTES,
    _make_step5_assets_find_handler,
    _make_step5_vector_search_handler,
)

APP_NAME = "event_commerce_ops_agent"

OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating France 3-2. "
    "Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, "
    "/tmp/wc-final/img03.jpg, /tmp/wc-final/img04.jpg. "
    "Match name: 'Argentina vs France'. Start: 2026-06-01T19:00:00Z. "
    "Process this batch."
)

# ---------------------------------------------------------------------------
# Seeded data
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

# ---------------------------------------------------------------------------
# Canned ReviewQueue fixture (includes a cross-assigned item for T1-d)
#   ast-0, ast-1 are in exploitation pool (strong similarity)
#   ast-2, ast-3 are in discovery pool (weak similarity)
# The fixture places ast-3 (a discovery-pool asset) in the exploitation list
# to test T1-d (cross-assignment recorded as violation, no crash).
# ---------------------------------------------------------------------------

_STEP5_CANNED_RESPONSE = {
    "event_id": "evt-demo-1",
    "exploitation": [
        {
            "asset_id": "ast-0",
            "queue_type": "exploitation",
            "rank": 1,
            "product_route": "tshirt",  # LLM chose tshirt — persist must ignore and use mechanical "poster"
            "rationale": "Messi in frame — identity match leads the queue",
        },
        {
            "asset_id": "ast-3",  # cross-assigned: ast-3 is in discovery pool
            "queue_type": "exploitation",
            "rank": 2,
            "product_route": "tshirt",
            "rationale": "cross-assigned violation test — should appear in membership_violations",
            # Note: this is ALSO intentionally different from ast-0's case:
            # ast-0 below uses product_route="tshirt" (LLM chose tshirt)
            # but persist must use the mechanical inferred_route "poster" — proving D-015.
        },
    ],
    "discovery": [
        {
            "asset_id": "ast-2",
            "queue_type": "discovery",
            "rank": 1,
            "product_route": "social_only",
            "rationale": "Emotional shot worth surfacing despite no match",
        },
    ],
    "strategy_summary": "Rich exploitation led by identity match; one discovery pick with emotional signal",
}


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
    except Exception:
        pass
    return events


# ---------------------------------------------------------------------------
# T-5.13: Tier-1 plumbing eval (deterministic, single run)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_5_tier1_trace():
    """Tier-1 plumbing eval — _FIXTURE_RESPONSE set, zero live queue calls."""
    with step5_fixture_response(_STEP5_CANNED_RESPONSE):
        with build_runner_with_step5_mock(_SEEDED_NARRATIVE) as (runner, mock_client):
            _seed_mock(mock_client)
            events = await _run_agent(runner)

    failures: list[str] = []
    trace_path = dump_trace(events, "step_5_tier1_trace")
    all_parts = _collect_parts(events)
    tool_calls = extract_tool_calls(events)
    tool_responses = extract_tool_responses(events)

    # (T1-e) coordinator dispatched run_event_pipeline exactly once
    pipeline_calls = [c for c in tool_calls if c["name"] == "run_event_pipeline"]
    if len(pipeline_calls) != 1:
        failures.append(
            f"(T1-e) Expected run_event_pipeline called 1 time, got {len(pipeline_calls)}. "
            f"Trace: {trace_path}"
        )

    # (T1-e) reasoning text present before first tool call
    first_tool_idx = next(
        (i for i, p in enumerate(all_parts) if p["kind"] == "tool_call"), None
    )
    text_before_tool = any(
        p["kind"] == "text" and i < (first_tool_idx if first_tool_idx is not None else len(all_parts))
        for i, p in enumerate(all_parts)
    )
    if not text_before_tool:
        failures.append(
            f"(T1-e) No reasoning text before tool call — CoT directive not firing. "
            f"Trace: {trace_path}"
        )

    # (T1-a) ReviewQueue parses from state via output_key
    pipeline_responses = [r for r in tool_responses if r.get("name") == "run_event_pipeline"]
    review_queue_raw = None
    queue_candidates_raw = None
    membership_violations_raw = None
    if pipeline_responses:
        resp = pipeline_responses[-1].get("response", {})
        result = resp.get("result", resp)
        review_queue_raw = result.get("review_queue")
        queue_candidates_raw = result.get("queue_candidates")
        membership_violations_raw = result.get("membership_violations")

    parsed_queue = None
    if review_queue_raw is None:
        failures.append(f"(T1-a) review_queue not in pipeline response. Trace: {trace_path}")
    else:
        try:
            parsed_queue = (
                ReviewQueue.model_validate_json(review_queue_raw)
                if isinstance(review_queue_raw, str)
                else ReviewQueue.model_validate(review_queue_raw)
            )
        except Exception as exc:
            failures.append(f"(T1-a) ReviewQueue parse failed: {exc}. Trace: {trace_path}")

    # (T1-b) prepare_queue_candidates split — exploitation vs. discovery membership
    if queue_candidates_raw is not None:
        expl_ids = {c["asset_id"] for c in queue_candidates_raw.get("exploitation", [])}
        disc_ids = {c["asset_id"] for c in queue_candidates_raw.get("discovery", [])}
        if expl_ids != STEP5_EXPLOITATION_IDS:
            failures.append(
                f"(T1-b) exploitation pool: expected {STEP5_EXPLOITATION_IDS}, got {expl_ids}. "
                f"Trace: {trace_path}"
            )
        if disc_ids != STEP5_DISCOVERY_IDS:
            failures.append(
                f"(T1-b) discovery pool: expected {STEP5_DISCOVERY_IDS}, got {disc_ids}. "
                f"Trace: {trace_path}"
            )
        # inferred_route carried for exploitation candidates
        for c in queue_candidates_raw.get("exploitation", []):
            expected_route = _STEP5_INFERRED_ROUTES.get(c["asset_id"])
            if c.get("inferred_route") != expected_route:
                failures.append(
                    f"(T1-b) inferred_route for {c['asset_id']}: expected {expected_route!r}, "
                    f"got {c.get('inferred_route')!r}. Trace: {trace_path}"
                )
    else:
        failures.append(f"(T1-b) queue_candidates not in pipeline response. Trace: {trace_path}")

    # (T1-c) persist_review_queue wrote correct save_queue_assignment calls
    call_log = mock_client.calls
    queue_writes = [
        (tn, args)
        for tn, args in call_log
        if tn == "update-many"
        and args.get("collection") == "assets"
        and "queue_type" in args.get("update", {}).get("$set", {})
    ]
    queue_write_map = {
        args["filter"]["asset_id"]: args["update"]["$set"]
        for tn, args in queue_writes
        if "asset_id" in args.get("filter", {})
    }

    # ast-0 persisted with mechanical route (poster), not LLM route
    if "ast-0" not in queue_write_map:
        failures.append(f"(T1-c) No queue write for ast-0. Trace: {trace_path}")
    else:
        actual_route = queue_write_map["ast-0"].get("product_route")
        if actual_route != "poster":
            failures.append(
                f"(T1-c) ast-0 route: expected 'poster' (mechanical), got {actual_route!r}. "
                f"Trace: {trace_path}"
            )

    # ast-1 not surfaced by the canned fixture → no queue write
    if "ast-1" in queue_write_map:
        failures.append(
            f"(T1-c) ast-1 not in canned fixture but got a queue write. Trace: {trace_path}"
        )

    # ast-2 persisted with LLM-chosen route (social_only)
    if "ast-2" not in queue_write_map:
        failures.append(f"(T1-c) No queue write for ast-2. Trace: {trace_path}")
    else:
        actual_route = queue_write_map["ast-2"].get("product_route")
        if actual_route != "social_only":
            failures.append(
                f"(T1-c) ast-2 route: expected 'social_only' (LLM-chosen), got {actual_route!r}. "
                f"Trace: {trace_path}"
            )

    # No status in any queue write
    for asset_id, set_block in queue_write_map.items():
        if "status" in set_block:
            failures.append(
                f"(T1-c) Queue write for {asset_id} contains 'status' — must not change status. "
                f"Trace: {trace_path}"
            )

    # (T1-d) cross-assigned item (ast-3) in membership_violations, no crash
    if membership_violations_raw is None:
        failures.append(
            f"(T1-d) membership_violations not in pipeline response. Trace: {trace_path}"
        )
    else:
        violations_flat = [str(v) for v in membership_violations_raw]
        if not any("ast-3" in v for v in violations_flat):
            failures.append(
                f"(T1-d) ast-3 (cross-assigned) not recorded in membership_violations: "
                f"{membership_violations_raw}. Trace: {trace_path}"
            )

    assert not failures, "\n".join(failures)
