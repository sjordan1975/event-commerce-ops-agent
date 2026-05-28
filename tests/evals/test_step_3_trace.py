"""Trace evals for the find_similar_assets capability.

T-3.14: Single-run outcome-shaped eval (9 assertions).
T-3.15: Pass-rate eval (≥95% over N runs, N defaults to 5 in CI, 20 for gate).

Scenario: Argentina vs France, same operator prompt as Step 2.
3 ingested assets: 2 get 5 historical neighbors each, 1 gets 0 neighbors
(exercises the discovery-queue empty-neighbor path).

The workflow asserts nine outcomes:
  (a) coordinator dispatched run_event_pipeline exactly once
  (b) outcome_type == "upset_victory" preserved (Step 2 regression guard)
  (c) _compute_image_embedding mock invoked once per ingested asset (3×)
  (d) update-many on assets setting embedding — 3 calls, each with a 3072-dim list
  (e) aggregate on assets with $vectorSearch — 3 calls with correct index + shape
  (f) update-many on assets setting similar_assets — 3 calls; empty-neighbor asset gets []
  (g) call order: ingest writes → context reads/writes → embedding updates → vector searches
  (h) reasoning text present before tool call (CoT directive)
  (i) _compute_image_embedding patch was actually used (mock call count)
"""

import math
import os
from datetime import datetime, timezone

import pytest
from google.genai import types

from tests.conftest import build_embedding_fixture
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
]

_PERF_AGG_DOCS = [
    {"_id": "poster", "total_orders": 300, "total_impressions": 18000, "count": 6},
    {"_id": "tshirt", "total_orders": 120, "total_impressions": 7000, "count": 4},
]

# 5 historical neighbors for assets 0 and 1; 0 neighbors for asset 2
_VECTOR_SEARCH_NEIGHBORS = [
    {
        "asset_id": f"past-asset-{j}",
        "event_id": "evt-past-1",
        "similarity": 0.85 - j * 0.05,
        "product_route": "poster",
        "scores": {"quality_score": 0.9},
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
    """Return seeded assets (no embeddings) for the current event's find call."""
    def handler(args: dict) -> list:
        f = args.get("filter", {})
        # find call from get_assets_for_event — return 3 assets without embeddings
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
                    "campaign_id": None,
                    "similar_assets": None,
                }
                for i in range(3)
            ]
        return []

    return handler


def _make_vector_search_handler():
    """Return neighbors for first 2 assets, empty for the 3rd."""
    _call_count = {"n": 0}

    def handler(args: dict) -> list:
        _call_count["n"] += 1
        # 3rd call → empty neighbors (discovery-queue path)
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
    events: list, mock_client, trace_label: str, embed_call_count: int
) -> list[str]:
    """Run all nine assertions. Returns list of failure messages (empty = pass)."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)
    all_parts = _collect_parts(events)
    tool_calls = extract_tool_calls(events)

    pipeline_calls = [c for c in tool_calls if c["name"] == "run_event_pipeline"]

    # (a) coordinator dispatched the pipeline exactly once
    if len(pipeline_calls) != 1:
        failures.append(
            f"(a) Expected run_event_pipeline called 1 time, got {len(pipeline_calls)}. "
            f"Trace: {trace_path}"
        )

    # (b) outcome_type preserved from Step 2
    if pipeline_calls:
        meta = pipeline_calls[0]["args"].get("event_metadata", {})
        if meta.get("outcome_type") != "upset_victory":
            failures.append(
                f"(b) outcome_type in event_metadata: expected 'upset_victory', "
                f"got {meta.get('outcome_type')!r}. Trace: {trace_path}"
            )

    # (c) embedding helper invoked once per ingested asset (3×) — captured before patch exits
    if embed_call_count != 3:
        failures.append(
            f"(c) _compute_image_embedding expected 3 calls, got {embed_call_count}. "
            f"Trace: {trace_path}"
        )

    # (d) 3 update-many on assets setting embedding (each with a 3072-dim list)
    embedding_updates = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "update-many" and a.get("collection") == "assets"
        and "embedding" in a.get("update", {}).get("$set", {})
    ]
    if len(embedding_updates) != 3:
        failures.append(
            f"(d) Expected 3 embedding update-many calls, got {len(embedding_updates)}. "
            f"Trace: {trace_path}"
        )
    for _, emb_args in embedding_updates:
        emb_list = emb_args["update"]["$set"]["embedding"]
        if not isinstance(emb_list, list) or len(emb_list) != 3072:
            failures.append(
                f"(d) Embedding list wrong shape: expected list[3072], "
                f"got {type(emb_list).__name__}[{len(emb_list) if isinstance(emb_list, list) else '?'}]. "
                f"Trace: {trace_path}"
            )
            break

    # (e) 3 aggregate on assets with $vectorSearch — correct index + shape
    vs_calls = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "aggregate" and a.get("collection") == "assets"
        and (a.get("pipeline") or [{}])[0].get("$vectorSearch") is not None
    ]
    if len(vs_calls) != 3:
        failures.append(
            f"(e) Expected 3 $vectorSearch aggregate calls, got {len(vs_calls)}. "
            f"Trace: {trace_path}"
        )
    for _, vs_args in vs_calls:
        vs_stage = vs_args["pipeline"][0]["$vectorSearch"]
        if vs_stage.get("index") != "assets_embedding_index":
            failures.append(
                f"(e) $vectorSearch index wrong: expected 'assets_embedding_index', "
                f"got {vs_stage.get('index')!r}. Trace: {trace_path}"
            )
        if vs_stage.get("path") != "embedding":
            failures.append(
                f"(e) $vectorSearch path wrong: expected 'embedding', "
                f"got {vs_stage.get('path')!r}. Trace: {trace_path}"
            )
        top_k = vs_stage.get("limit", 0)
        num_candidates = vs_stage.get("numCandidates", 0)
        if num_candidates < 10 * top_k:
            failures.append(
                f"(e) numCandidates {num_candidates} < 10 * top_k {top_k}. "
                f"Trace: {trace_path}"
            )

    # (f) 3 update-many on assets setting similar_assets; empty-neighbor asset gets []
    sim_updates = [
        (tn, a) for tn, a in mock_client.calls
        if tn == "update-many" and a.get("collection") == "assets"
        and "similar_assets" in a.get("update", {}).get("$set", {})
    ]
    if len(sim_updates) != 3:
        failures.append(
            f"(f) Expected 3 similar_assets update-many calls, got {len(sim_updates)}. "
            f"Trace: {trace_path}"
        )
    # At least one call must have similar_assets=[] (the empty-neighbors asset)
    empty_sim_updates = [
        a for _, a in sim_updates
        if a["update"]["$set"]["similar_assets"] == []
    ]
    if not empty_sim_updates:
        failures.append(
            f"(f) No similar_assets=[] update found — empty-neighbor asset not persisted correctly. "
            f"Trace: {trace_path}"
        )

    # (g) call order: ingest writes before context reads/writes before similarity writes
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
    if ingest_insert_idx is None:
        failures.append(f"(g) No insert-many on assets recorded. Trace: {trace_path}")
    elif context_event_read_idx is None:
        failures.append(f"(g) No find on events by event_id recorded. Trace: {trace_path}")
    elif first_embedding_update_idx is None:
        failures.append(f"(g) No embedding update-many recorded. Trace: {trace_path}")
    elif not (ingest_insert_idx < context_event_read_idx < first_embedding_update_idx):
        failures.append(
            f"(g) Call order wrong: ingest_insert_idx={ingest_insert_idx}, "
            f"context_event_read_idx={context_event_read_idx}, "
            f"first_embedding_update_idx={first_embedding_update_idx}. "
            f"Expected ingest < context < similarity. Trace: {trace_path}"
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

    # (i) _compute_image_embedding patch was actually used — proven by call count > 0
    if embed_call_count == 0:
        failures.append(
            f"(i) _compute_image_embedding mock was never called — embedding patch not used. "
            f"Trace: {trace_path}"
        )

    return failures


# ---------------------------------------------------------------------------
# T-3.14: Single-run eval
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_3_single_run():
    """Single-run outcome-shaped trace eval for find_similar_assets."""
    import src.capabilities.similarity as sim_module

    with build_runner_with_mock_db() as (runner, mock_client):
        _seed_mock(mock_client)
        events = await _run_agent(runner)
        # Capture call count before patch is removed by context manager exit
        embed_call_count = sim_module._compute_image_embedding.call_count

    failures = _assert_single_run(events, mock_client, "step_3_single_run", embed_call_count)
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# T-3.15: Pass-rate eval (N=20, ≥95% threshold)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_3_pass_rate():
    """Pass-rate eval: ≥95% of N runs must satisfy all nine assertions (D-020)."""
    n = int(os.environ.get("EVAL_REPEAT", "5"))
    passes = 0
    run_failures: list[tuple[int, list[str]]] = []

    for i in range(n):
        import src.capabilities.similarity as sim_module

        with build_runner_with_mock_db() as (runner, mock_client):
            _seed_mock(mock_client)
            events = await _run_agent(runner)
            embed_call_count = sim_module._compute_image_embedding.call_count
        failures = _assert_single_run(events, mock_client, f"step_3_pass_rate_run_{i}", embed_call_count)
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
