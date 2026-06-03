"""build_event_context — agent-facing capability for Step 2."""

import asyncio
import logging
import os
import time
import types

logger = logging.getLogger(__name__)

from pydantic import BaseModel

from google import genai
from google.genai import types as genai_types

from src.db.events import find_past_events_by_outcome, get_event, update_event_narrative
from src.db.performance import aggregate_performance_for_events
from src.db.player_context import find_players_for_teams
from src.errors import PreconditionError
from src.models import EventNarrative, HistoricalBaseline, Player
from src.prompt_loader import load_prompt


def _run_narrative_llm(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Single-call Gemini generate_content with structured output. Internal."""
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    model = os.environ.get("GEMINI_NARRATIVE_MODEL", "gemini-2.5-flash-lite")
    logger.info("narrative_llm start  model=%s schema=%s", model, schema.__name__)
    t0 = time.perf_counter()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    result = schema.model_validate_json(response.text)
    logger.info("narrative_llm done   schema=%s chars=%d latency=%.1fs",
                schema.__name__, len(response.text), time.perf_counter() - t0)
    return result


def _build_cohort_summary(past_events: list, outcome_type: str) -> str:
    if not past_events:
        return "(no past events of this outcome_type — historical_baseline.notes should say so)"
    return f"{len(past_events)} past event(s) with outcome_type='{outcome_type}'"


def _build_player_block(players: list[Player]) -> str:
    if not players:
        return "(no seeded players for these teams — key_figures should be empty)"
    lines = []
    for p in players:
        lines.append(
            f"- {p.name} ({p.team}, {p.position}, commercial_signal: {p.commercial_signal})"
        )
        lines.append(f"  Facts: {'; '.join(p.notable_facts)}")
        lines.append(f"  Career: {p.career_milestones}")
    return "\n".join(lines)


async def build_event_context(event_id: str) -> dict:
    """Builds a structured narrative for an ingested event.

    Aggregates the event record, the historical performance baseline for events
    of the same outcome_type, and player biographical facts from player_context.
    Calls Gemini to compose an EventNarrative (typed structured output) and
    persists it onto the events document.

    Returns the narrative as a dict with keys:
        event_id, narrative_angle, key_figures, commercial_timing, historical_baseline

    Raises PreconditionError if the event is not found (call ingest_event_batch first).

    Independent of find_similar_assets and score_assets_with_vision — order among
    those three is your call; pick what makes sense for the situation. The narrative
    is consumed by propose_review_queue (required precondition) and by
    draft_campaigns_for_queue (copy substrate).
    """
    event = await get_event(event_id)
    if event is None:
        raise PreconditionError(
            capability="build_event_context",
            context=event_id,
            missing={"event": "event not found; call ingest_event_batch first"},
        )

    past_events = await find_past_events_by_outcome(event.outcome_type, event_id)
    perf = await aggregate_performance_for_events([e.event_id for e in past_events])

    baseline = HistoricalBaseline(
        outcome_type=event.outcome_type,
        past_event_count=perf["past_event_count"],
        top_product_route=perf["top_product_route"],
        total_orders=perf["total_orders"],
        total_impressions=perf["total_impressions"],
        notes=(
            "no historical data yet"
            if perf["past_event_count"] == 0
            else (
                f"{perf['past_event_count']} past event(s); "
                f"top route: {perf['top_product_route']}"
            )
        ),
    )

    players = await find_players_for_teams(event.home_team, event.away_team)

    fmt_event = types.SimpleNamespace(
        name=event.name,
        home_team=event.home_team,
        away_team=event.away_team,
        final_score=event.final_score,
        outcome_type=event.outcome_type,
        timeliness=event.timeliness,
        location=event.location or "(unspecified)",
    )

    prompt = load_prompt("build_event_context").format(
        event=fmt_event,
        event_id=event_id,
        cohort_summary=_build_cohort_summary(past_events, event.outcome_type),
        baseline=baseline,
        player_block=_build_player_block(players),
    )

    narrative: EventNarrative = await asyncio.to_thread(
        _run_narrative_llm, prompt, EventNarrative
    )

    await update_event_narrative(event_id, narrative)

    return narrative.model_dump(mode="json")
