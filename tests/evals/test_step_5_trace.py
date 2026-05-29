"""Tier-1 plumbing eval for propose_review_queue (T-5.13).

Dispatches the workflow directly (no coordinator) with _FIXTURE_RESPONSE set and all
LLM surfaces patched — zero live calls, no GOOGLE_API_KEY needed. This is the CI
ship gate; it must not fail on AI-infra flakiness (D-029).

Direct-dispatch pattern validated by spike/adk_llm_node_queue_spike.py (mocked path,
Claims A–D). Assertion T1-e (coordinator dispatch + CoT text) is intentionally omitted
— it is a coordinator assertion, not a queue assertion, and is already covered by
Steps 2-4 trace evals (assertions a and g there). Running Tier 2 (test_step_5_coherence.py)
with a live coordinator covers that path when deliberately executed.

Assertions (T1-a through T1-d):
  (T1-a) ReviewQueue parses from state["review_queue"] via ADK output_key.
  (T1-b) prepare_queue_candidates split correct: ast-0/ast-1 in exploitation pool,
         ast-2/ast-3 in discovery pool; inferred_route carried for exploitation.
  (T1-c) persist_review_queue issued save_queue_assignment per surfaced item:
         exploitation route = mechanical inferred_route (not LLM's "tshirt" — proves D-015);
         discovery route = canned LLM route; ast-1 (unsurfaced) gets no write;
         no status key in any queue write.
  (T1-d) Cross-assigned item (ast-3) recorded in membership_violations, no crash.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agent import WORKFLOW_NAME, build_workflow
from src.models import EventNarrative, ReviewQueue
from tests.conftest import build_embedding_fixture
from tests.evals.conftest import (
    _MockMCPClient,
    STEP5_DISCOVERY_IDS,
    STEP5_EXPLOITATION_IDS,
    _STEP5_INFERRED_ROUTES,
    _make_step5_assets_find_handler,
    _make_step5_vector_search_handler,
    _step5_vision_provider,
    step5_fixture_response,
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
#
# ast-0: LLM chose product_route="tshirt" — but persist MUST use the mechanical
#   inferred_route="poster" (D-015). This proves the D-015 invariant end-to-end.
# ast-3: placed in exploitation by LLM but is in discovery pool → membership_violation.
# ---------------------------------------------------------------------------

_STEP5_CANNED_RESPONSE = {
    "event_id": "evt-demo-1",
    "exploitation": [
        {
            "asset_id": "ast-0",
            "queue_type": "exploitation",
            "rank": 1,
            "product_route": "tshirt",  # LLM chose tshirt — persist MUST use mechanical "poster"
            "rationale": "Messi in frame — identity match leads the queue",
        },
        {
            "asset_id": "ast-3",  # cross-assigned: ast-3 is in discovery pool
            "queue_type": "exploitation",
            "rank": 2,
            "product_route": "tshirt",
            "rationale": "cross-assigned violation test — should appear in membership_violations",
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

# ---------------------------------------------------------------------------
# Mock DB handlers
# ---------------------------------------------------------------------------

def _make_events_find_handler():
    def handler(args: dict) -> list:
        f = args.get("filter", {})
        event_id_filter = f.get("event_id")
        outcome_filter = f.get("outcome_type")

        if isinstance(event_id_filter, str):
            # Return seeded event with whatever event_id was generated by ingest
            return [{
                **{k: v for k, v in {
                    "event_id": event_id_filter,
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
                }.items()},
            }]

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
# T-5.13: Tier-1 plumbing eval (direct workflow dispatch, fully offline)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_5_tier1_trace():
    """Tier-1 plumbing eval — direct workflow dispatch, zero live calls, no API key."""
    narrative_fixture = EventNarrative.model_validate(_SEEDED_NARRATIVE)
    mock_client = _MockMCPClient()
    _seed_mock(mock_client)

    with (
        step5_fixture_response(_STEP5_CANNED_RESPONSE),
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch("src.db.player_context.get_client", return_value=mock_client),
        patch("src.capabilities.context._run_narrative_llm", return_value=narrative_fixture),
        patch(
            "src.capabilities.similarity._compute_image_embedding",
            return_value=build_embedding_fixture(),
        ),
        patch(
            "src.capabilities.scoring._score_asset_with_vision",
            side_effect=_step5_vision_provider,
        ),
    ):
        workflow = build_workflow()
        session_service = InMemorySessionService()
        session = await session_service.create_session(
            app_name=WORKFLOW_NAME,
            user_id="eval_user",
            state={
                "images": [
                    "/tmp/wc-final/img01.jpg",
                    "/tmp/wc-final/img02.jpg",
                    "/tmp/wc-final/img03.jpg",
                    "/tmp/wc-final/img04.jpg",
                ],
                "event_metadata": {
                    "name": "Argentina vs France",
                    "home_team": "Argentina",
                    "away_team": "France",
                    "final_score": "3-2",
                    "start_date": "2026-06-01T19:00:00Z",
                    "outcome_type": "upset_victory",
                },
            },
        )
        runner = Runner(
            app_name=WORKFLOW_NAME,
            node=workflow,
            session_service=session_service,
        )
        trigger = types.Content(role="user", parts=[types.Part(text="run pipeline")])
        try:
            async for _event in runner.run_async(
                user_id="eval_user",
                session_id=session.id,
                new_message=trigger,
            ):
                pass
        except ValueError as exc:
            if "Token was created in a different Context" not in str(exc):
                raise
        except Exception:
            pass

        final = await session_service.get_session(
            app_name=WORKFLOW_NAME,
            user_id="eval_user",
            session_id=session.id,
        )
        state = dict(final.state) if final else {}

    failures: list[str] = []

    # (T1-a) ReviewQueue parses from state["review_queue"] via ADK output_key
    review_queue_raw = state.get("review_queue")
    if review_queue_raw is None:
        failures.append("(T1-a) review_queue not in pipeline state")
    else:
        try:
            parsed_queue = (
                ReviewQueue.model_validate_json(review_queue_raw)
                if isinstance(review_queue_raw, str)
                else ReviewQueue.model_validate(review_queue_raw)
            )
        except Exception as exc:
            failures.append(f"(T1-a) ReviewQueue parse failed: {exc}")
            parsed_queue = None

    # (T1-b) prepare_queue_candidates split correct
    queue_candidates = state.get("queue_candidates")
    if queue_candidates is None:
        failures.append("(T1-b) queue_candidates not in pipeline state")
    else:
        expl_ids = {c["asset_id"] for c in queue_candidates.get("exploitation", [])}
        disc_ids = {c["asset_id"] for c in queue_candidates.get("discovery", [])}
        if expl_ids != STEP5_EXPLOITATION_IDS:
            failures.append(
                f"(T1-b) exploitation pool: expected {STEP5_EXPLOITATION_IDS}, got {expl_ids}"
            )
        if disc_ids != STEP5_DISCOVERY_IDS:
            failures.append(
                f"(T1-b) discovery pool: expected {STEP5_DISCOVERY_IDS}, got {disc_ids}"
            )
        for c in queue_candidates.get("exploitation", []):
            expected_route = _STEP5_INFERRED_ROUTES.get(c["asset_id"])
            if c.get("inferred_route") != expected_route:
                failures.append(
                    f"(T1-b) inferred_route for {c['asset_id']}: "
                    f"expected {expected_route!r}, got {c.get('inferred_route')!r}"
                )

    # (T1-c) persist_review_queue called save_queue_assignment correctly
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

    # ast-0: persist must use mechanical route "poster", not LLM's "tshirt" (D-015)
    if "ast-0" not in queue_write_map:
        failures.append("(T1-c) No queue write for ast-0")
    else:
        actual_route = queue_write_map["ast-0"].get("product_route")
        if actual_route != "poster":
            failures.append(
                f"(T1-c) ast-0 route: expected 'poster' (mechanical D-015), got {actual_route!r}"
            )

    # ast-1 not in canned fixture → no queue write (unsurfaced exploitation asset)
    if "ast-1" in queue_write_map:
        failures.append("(T1-c) ast-1 not surfaced but got a queue write")

    # ast-2: discovery item → persist with LLM-chosen route "social_only"
    if "ast-2" not in queue_write_map:
        failures.append("(T1-c) No queue write for ast-2")
    else:
        actual_route = queue_write_map["ast-2"].get("product_route")
        if actual_route != "social_only":
            failures.append(
                f"(T1-c) ast-2 route: expected 'social_only' (LLM-chosen), got {actual_route!r}"
            )

    # No status in any queue write
    for asset_id, set_block in queue_write_map.items():
        if "status" in set_block:
            failures.append(
                f"(T1-c) Queue write for {asset_id} contains 'status' — "
                "must not change status (D-029)"
            )

    # (T1-d) cross-assigned item (ast-3) in membership_violations, no crash
    membership_violations = state.get("membership_violations")
    if membership_violations is None:
        failures.append("(T1-d) membership_violations not in pipeline state")
    else:
        violations_flat = [str(v) for v in membership_violations]
        if not any("ast-3" in v for v in violations_flat):
            failures.append(
                f"(T1-d) ast-3 (cross-assigned) not recorded in membership_violations: "
                f"{membership_violations}"
            )

    assert not failures, "\n".join(failures)
