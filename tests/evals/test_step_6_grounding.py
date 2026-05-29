"""Optional grounding probe for draft_campaigns_for_queue (T-6.13).

Runs the real _draft_copy_for_asset (live Gemini call, GOOGLE_API_KEY required)
against the seeded narrative to check copy quality. NOT a CI gate — run deliberately.

Assertions:
  (a) Grounding: for an asset whose detected_subjects contains the key figure,
      the generated headline or caption contains that token (name or narrative angle term).
  (b) Hallucination guard: for the seeded crowd-shot asset (empty detected_subjects),
      the copy does NOT name a key figure absent from that frame.

If copy is generic or the guard fails, climb the remediation ladder per
docs/evaluation-strategy.md: prompt language first, then model swap (GEMINI_DRAFT_MODEL).
"""

import os
from unittest.mock import patch
from datetime import datetime, timezone

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agent import WORKFLOW_NAME, build_workflow
from src.models import EventNarrative
from tests.conftest import build_embedding_fixture
from tests.evals.conftest import (
    _MockMCPClient,
    STEP6_CROWD_ASSET_ID,
    _make_step6_assets_find_handler,
    _make_step5_vector_search_handler,
    _step5_vision_provider,
    step5_fixture_response,
    dump_trace,
)
from tests.evals.test_step_6_trace import (
    _SEEDED_NARRATIVE,
    _PAST_EVENTS,
    _PLAYERS,
    _PERF_AGG_DOCS,
    _STEP5_CANNED_RESPONSE,
    _make_events_find_handler,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="Grounding probe requires GOOGLE_API_KEY — run deliberately, not in CI",
)

# Key figure name and distinctive angle term from the seeded narrative.
_GROUNDING_TOKEN = "Messi"
_ANGLE_TOKEN = "Argentina"

# Key figures named in the narrative (must NOT appear in crowd-shot copy).
_KEY_FIGURE_NAMES = {"Lionel Messi", "Kylian Mbappé", "Messi", "Mbappé"}


def _seed_mock(mock_client: _MockMCPClient) -> None:
    mock_client.register("find", "events", _make_events_find_handler())
    mock_client.register("find", "assets", _make_step6_assets_find_handler())
    mock_client.register("find", "player_context", _PLAYERS)
    mock_client.register("aggregate", "performance", _PERF_AGG_DOCS)
    mock_client.register_vector_search("assets", _make_step5_vector_search_handler())


@pytest.mark.anyio
async def test_step_6_grounding_probe():
    """Live _draft_copy_for_asset: grounding holds, hallucination guard holds."""
    narrative_fixture = EventNarrative.model_validate(_SEEDED_NARRATIVE)
    mock_client = _MockMCPClient()
    _seed_mock(mock_client)

    events: list = []

    with (
        step5_fixture_response(_STEP5_CANNED_RESPONSE),
        # _draft_copy_for_asset is NOT patched — this is the live run
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
            async for event in runner.run_async(
                user_id="eval_user",
                session_id=session.id,
                new_message=trigger,
            ):
                events.append(event)
        except ValueError as exc:
            if "Token was created in a different Context" not in str(exc):
                raise

        final = await session_service.get_session(
            app_name=WORKFLOW_NAME,
            user_id="eval_user",
            session_id=session.id,
        )
        state = dict(final.state) if final else {}

    drafts = state.get("drafts", [])
    failures: list[str] = []

    if not drafts:
        failures.append("No drafts in pipeline state — pipeline did not reach Step 6")
        dump_trace(events, "step_6_grounding_no_drafts")
        assert not failures, "\n".join(failures)

    # (a) Grounding: asset with Messi in detected_subjects → copy contains grounding token
    messi_drafts = [
        d for d in drafts
        if d.get("asset_id") in {"ast-0", "ast-2"}  # both have detected_subjects=["Lionel Messi"]
    ]
    for d in messi_drafts:
        text = (d.get("headline", "") + " " + d.get("caption", "")).lower()
        if _GROUNDING_TOKEN.lower() not in text and _ANGLE_TOKEN.lower() not in text:
            failures.append(
                f"(a) Grounding failure for {d['asset_id']}: headline/caption lacks "
                f"'{_GROUNDING_TOKEN}' or '{_ANGLE_TOKEN}'. Got: {d.get('headline')!r}"
            )

    # (b) Hallucination guard: crowd-shot asset → copy must NOT name a key figure
    crowd_drafts = [d for d in drafts if d.get("asset_id") == STEP6_CROWD_ASSET_ID]
    for d in crowd_drafts:
        text = d.get("headline", "") + " " + d.get("caption", "")
        named = [name for name in _KEY_FIGURE_NAMES if name in text]
        if named:
            failures.append(
                f"(b) Hallucination guard failed for crowd shot {d['asset_id']}: "
                f"copy names {named!r} but detected_subjects is empty. "
                f"Headline: {d.get('headline')!r}"
            )

    if failures:
        dump_trace(events, "step_6_grounding_failure")

    assert not failures, "\n".join(failures)
