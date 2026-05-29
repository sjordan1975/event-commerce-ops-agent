"""Tier-1 plumbing eval for draft_campaigns_for_queue (T-6.12).

Dispatches the workflow directly (no coordinator) with _draft_copy_for_asset
patched and all LLM surfaces patched — zero live calls, no GOOGLE_API_KEY needed.
This is the CI ship gate; must not fail on AI-infra flakiness.

Single run is authoritative (deterministic): _draft_copy_for_asset is mocked, so
every run yields the same writes.

Assertions:
  (T1-a) One campaigns insert-many per queued asset, correct product_type/platform_target.
  (T1-b) One approvals insert-many per draft, status="pending", reviewer_notes=None,
          linked campaign_id/asset_id.
  (T1-c) assets update-many sets status="campaign_draft_created" + campaign_id per
          drafted asset; un-surfaced asset (ast-3) gets NO campaign/approval/status write.
  (T1-d) Route mapping correct: poster→shopify, tshirt→shopify, social_only→social.
  (T1-e) Pipeline state contains campaign_ids, approval_ids, drafts; count == queued count.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agent import WORKFLOW_NAME, build_workflow
from src.models import EventNarrative
from tests.conftest import build_embedding_fixture
from tests.evals.conftest import (
    _MockMCPClient,
    _CANNED_COPY,
    STEP6_QUEUED_IDS,
    STEP6_UNSURFACED_ID,
    _make_step6_assets_find_handler,
    _make_step5_vector_search_handler,
    _step5_vision_provider,
    patch_draft_copy_for_asset,
    step5_fixture_response,
)

# ---------------------------------------------------------------------------
# Seeded data (same Argentina-vs-France event as Steps 2–5)
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

# Step 5 canned ReviewQueue: surfaces ast-0 (exploitation), ast-2 (discovery).
# ast-1 and ast-3 intentionally unsurfaced by Step 5.
# Step 6 reads the pre-seeded handler directly (not from what Step 5 wrote) so
# the exact Step 5 fixture only needs to be a valid ReviewQueue, not a mirror of
# the Step 6 pre-seed.
_STEP5_CANNED_RESPONSE = {
    "event_id": "evt-demo-1",
    "exploitation": [
        {
            "asset_id": "ast-0",
            "queue_type": "exploitation",
            "rank": 1,
            "product_route": "poster",
            "rationale": "Messi in frame — identity match leads the queue",
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
    "strategy_summary": "Rich exploitation led by identity match; one discovery pick",
}

# Expected route mapping for the Step 6 queued assets (from the pre-seed).
_EXPECTED_ROUTES = {
    "ast-0": ("poster", "shopify"),
    "ast-1": ("tshirt", "shopify"),
    "ast-2": (None, "social"),
    "ast-4": (None, "social"),
}


# ---------------------------------------------------------------------------
# Mock DB setup
# ---------------------------------------------------------------------------

def _make_events_find_handler():
    def handler(args: dict) -> list:
        f = args.get("filter", {})
        event_id_filter = f.get("event_id")
        outcome_filter = f.get("outcome_type")

        if isinstance(event_id_filter, str):
            return [{
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
    mock_client.register("find", "assets", _make_step6_assets_find_handler())
    mock_client.register("find", "player_context", _PLAYERS)
    mock_client.register("aggregate", "performance", _PERF_AGG_DOCS)
    mock_client.register_vector_search("assets", _make_step5_vector_search_handler())


# ---------------------------------------------------------------------------
# T-6.12: Tier-1 plumbing eval
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_6_tier1_trace():
    """Tier-1 plumbing eval — direct workflow dispatch, zero live calls, no API key."""
    narrative_fixture = EventNarrative.model_validate(_SEEDED_NARRATIVE)
    mock_client = _MockMCPClient()
    _seed_mock(mock_client)

    with (
        step5_fixture_response(_STEP5_CANNED_RESPONSE),
        patch_draft_copy_for_asset(_CANNED_COPY),
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch("src.db.player_context.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
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

        final = await session_service.get_session(
            app_name=WORKFLOW_NAME,
            user_id="eval_user",
            session_id=session.id,
        )
        state = dict(final.state) if final else {}

    failures: list[str] = []
    call_log = mock_client.calls

    # ---------------------------------------------------------------------------
    # Build indexes of campaign/approval/status writes
    # ---------------------------------------------------------------------------
    campaign_inserts = [
        args["documents"][0]
        for tn, args in call_log
        if tn == "insert-many" and args.get("collection") == "campaigns"
    ]
    approval_inserts = [
        args["documents"][0]
        for tn, args in call_log
        if tn == "insert-many" and args.get("collection") == "approvals"
    ]
    # Only Step 6 writes status="campaign_draft_created" — filter out Step 4's "scored" writes.
    status_writes = {
        args["filter"]["asset_id"]: args["update"]["$set"]
        for tn, args in call_log
        if tn == "update-many"
        and args.get("collection") == "assets"
        and args.get("update", {}).get("$set", {}).get("status") == "campaign_draft_created"
        and "asset_id" in args.get("filter", {})
    }
    campaign_by_asset = {c["asset_id"]: c for c in campaign_inserts}
    approval_by_campaign = {a["campaign_id"]: a for a in approval_inserts}

    # ---------------------------------------------------------------------------
    # (T1-a) One campaigns insert-many per queued asset; correct product_type/platform_target
    # ---------------------------------------------------------------------------
    drafted_asset_ids = set(campaign_by_asset.keys())
    if drafted_asset_ids != STEP6_QUEUED_IDS:
        failures.append(
            f"(T1-a) drafted assets: expected {sorted(STEP6_QUEUED_IDS)}, got {sorted(drafted_asset_ids)}"
        )

    for asset_id, (exp_product_type, exp_platform) in _EXPECTED_ROUTES.items():
        if asset_id not in campaign_by_asset:
            failures.append(f"(T1-a) No campaign insert for {asset_id}")
            continue
        camp = campaign_by_asset[asset_id]
        if camp.get("product_type") != exp_product_type:
            failures.append(
                f"(T1-a) {asset_id} product_type: expected {exp_product_type!r}, got {camp.get('product_type')!r}"
            )
        if camp.get("platform_target") != exp_platform:
            failures.append(
                f"(T1-a) {asset_id} platform_target: expected {exp_platform!r}, got {camp.get('platform_target')!r}"
            )
        # Canned copy was used
        if camp.get("generated_copy", {}).get("headline") != _CANNED_COPY.headline:
            failures.append(
                f"(T1-a) {asset_id} headline mismatch: expected {_CANNED_COPY.headline!r}"
            )

    # ---------------------------------------------------------------------------
    # (T1-b) One approvals insert-many per draft; status="pending", reviewer_notes=None
    # ---------------------------------------------------------------------------
    if len(approval_inserts) != len(STEP6_QUEUED_IDS):
        failures.append(
            f"(T1-b) approval count: expected {len(STEP6_QUEUED_IDS)}, got {len(approval_inserts)}"
        )
    for apr in approval_inserts:
        if apr.get("status") != "pending":
            failures.append(f"(T1-b) approval {apr.get('approval_id')}: status != 'pending'")
        if apr.get("reviewer_notes") is not None:
            failures.append(f"(T1-b) approval {apr.get('approval_id')}: reviewer_notes should be None")
        asset_id = apr.get("asset_id")
        if asset_id not in drafted_asset_ids:
            failures.append(f"(T1-b) approval links to un-drafted asset_id: {asset_id!r}")

    # ---------------------------------------------------------------------------
    # (T1-c) assets update-many for each drafted asset; un-surfaced gets no write
    # ---------------------------------------------------------------------------
    for asset_id in STEP6_QUEUED_IDS:
        if asset_id not in status_writes:
            failures.append(f"(T1-c) No status write for drafted asset {asset_id}")
            continue
        s = status_writes[asset_id]
        if s.get("status") != "campaign_draft_created":
            failures.append(
                f"(T1-c) {asset_id} status: expected 'campaign_draft_created', got {s.get('status')!r}"
            )
        if "campaign_id" not in s:
            failures.append(f"(T1-c) {asset_id} status write missing campaign_id")

    if STEP6_UNSURFACED_ID in status_writes:
        failures.append(
            f"(T1-c) un-surfaced asset {STEP6_UNSURFACED_ID} received a status write — should be skipped"
        )
    if STEP6_UNSURFACED_ID in campaign_by_asset:
        failures.append(
            f"(T1-c) un-surfaced asset {STEP6_UNSURFACED_ID} received a campaign insert — should be skipped"
        )

    # ---------------------------------------------------------------------------
    # (T1-d) Route mapping correct across poster/tshirt/social_only
    # ---------------------------------------------------------------------------
    for asset_id, (exp_product_type, exp_platform) in _EXPECTED_ROUTES.items():
        if asset_id in campaign_by_asset:
            camp = campaign_by_asset[asset_id]
            actual = (camp.get("product_type"), camp.get("platform_target"))
            expected = (exp_product_type, exp_platform)
            if actual != expected:
                failures.append(
                    f"(T1-d) {asset_id} route: expected {expected}, got {actual}"
                )

    # ---------------------------------------------------------------------------
    # (T1-e) Pipeline state carries campaign_ids/approval_ids/drafts
    # ---------------------------------------------------------------------------
    campaign_ids = state.get("campaign_ids")
    approval_ids = state.get("approval_ids")
    drafts = state.get("drafts")

    if not campaign_ids:
        failures.append("(T1-e) campaign_ids missing or empty in pipeline state")
    if not approval_ids:
        failures.append("(T1-e) approval_ids missing or empty in pipeline state")
    if not drafts:
        failures.append("(T1-e) drafts missing or empty in pipeline state")
    if campaign_ids and len(campaign_ids) != len(STEP6_QUEUED_IDS):
        failures.append(
            f"(T1-e) campaign_ids count: expected {len(STEP6_QUEUED_IDS)}, got {len(campaign_ids)}"
        )

    if failures:
        import json
        state_summary = {k: v for k, v in state.items() if k in ("campaign_ids", "approval_ids", "drafts")}
        print("\nState summary:", json.dumps(state_summary, default=str, indent=2))
        print(f"Calls: {len(call_log)} total")

    assert not failures, "\n".join(failures)
