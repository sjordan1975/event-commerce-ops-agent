"""Coordinator end-to-end smoke eval (the project's one e2e tier).

This is the ONLY eval that exercises the coordinator: it drives the real
coordinator LLM with a natural-language operator prompt, which dispatches
`run_event_pipeline` → the full 9-node workflow graph. Every other capability
eval (Steps 5–8) dispatches the workflow directly, bypassing the coordinator.
So this file owns the "NL in → pipeline ran end-to-end" smoke; per-capability
agentic behavior is owned by the direct-dispatch evals, and ingest's
deterministic writes are owned by tests/test_step_1.py.

Because it runs the whole graph, the seed must satisfy every node's reads
(_seed_mock_for_full_pipeline) — that's the maintenance contract, enforced by
the completion assertion: if a node aborts the pipeline, the eval fails and
names the aborting node + exception rather than silently passing on a partial
trace. See `_assert_pipeline_completed`.

The agent must:
  (a) call run_event_pipeline exactly once
  (b) extract correct fields from natural language (hardest: outcome_type)
  (c) drive two MongoDB insert-many calls (events + assets) — smoke end-state
  (d) produce a non-null timeliness float in [0, 1] on the event document
  (e) emit reasoning text before the tool call (CoT directive from coordinator_system prompt)
  (f) emit non-empty terminal text after the tool returns
  (g) the pipeline ran to completion (run_event_pipeline returned)
"""

import math
import os
from unittest.mock import patch

import pytest
from google.genai import types

import contextlib

from tests.conftest import build_valid_event_narrative, build_valid_generated_copy
from tests.evals.conftest import (
    _collect_parts,
    _make_step6_assets_find_handler,
    build_runner_with_step6_mock,
    dump_trace,
    extract_tool_calls,
    patch_draft_copy_for_asset,
    step5_fixture_response,
)

# Empty canned ReviewQueue for the propose_review_queue LLM node — persist_review_queue
# records membership violations and never raises (queue.py), so an empty queue is safe:
# the pipeline completes, and this smoke asserts nothing about queue composition.
_EMPTY_REVIEW_QUEUE = {
    "event_id": "smoke",
    "exploitation": [],
    "discovery": [],
    "strategy_summary": "smoke: empty queue",
}


@contextlib.contextmanager
def _stub_internal_llms(mock_client):
    """Make everything except the coordinator's own 2 calls (dispatch + terminal)
    deterministic, so the smoke exercises coordinator behavior and nothing else.

    - Stubs workflow-internal LLMs (narrative, propose_review_queue node, per-asset
      copy) — owned by their own capability evals; shrinks the transient-503 surface.
    - Patches approvals.get_client: per coordinator_system.md the coordinator advances
      to request_human_approval after presenting the pipeline result, which reads the
      approvals collection. Routed to the mock (empty pending → empty batch → clean
      suspend) so it doesn't hit a real DB. request_human_approval suspends (returns
      None), which ends run_async normally — the smoke's natural terminus.
    """
    mock_client.register("find", "approvals", [])
    with (
        step5_fixture_response(_EMPTY_REVIEW_QUEUE),
        patch_draft_copy_for_asset(build_valid_generated_copy()),
        patch(
            "src.capabilities.context._run_narrative_llm",
            return_value=build_valid_event_narrative(),
        ),
        patch("src.db.approvals.get_client", return_value=mock_client),
    ):
        yield

APP_NAME = "event_commerce_ops_agent"

OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating heavy favorites France 3-2. "
    "Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, /tmp/wc-final/img03.jpg. "
    "Match started 2026-05-27T19:00:00Z. Match name: 'Argentina vs France'. "
    "Process this batch."
)

# Dir-path variant: operator gives a directory instead of individual file paths.
# The coordinator must call list_images first, then run_event_pipeline with the
# returned files list — exercising coordinator_system.md §34.
DIR_PATH_OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating heavy favorites France 3-2. "
    "All match photos are in /tmp/wc-final/. "
    "Match started 2026-05-27T19:00:00Z. Match name: 'Argentina vs France'. "
    "Process this batch."
)

_FAKE_LIST_IMAGES_RESULT = {
    "files": [
        "/tmp/wc-final/img01.jpg",
        "/tmp/wc-final/img02.jpg",
        "/tmp/wc-final/img03.jpg",
    ],
    "count": 3,
}


def _seed_mock_for_full_pipeline(mock_client) -> None:
    """Seed every workflow node's reads so the full pipeline runs to completion.

    The coordinator dispatches `run_event_pipeline` → the 9-node graph (D-024):
    ingest → context → find_similar_assets → score → prepare_queue →
    propose_review_queue → persist_review_queue → draft_campaigns_for_queue.
    Each node that reads Mongo needs a handler here; a gap aborts the pipeline
    and the completion assertion fails, naming the node. The event_id is dynamic
    (fresh uuid per run), so handlers key off whichever event_id the node asks for.

    Note: the LLM node (propose_review_queue) and the per-asset copy LLM are
    fixtured by the caller via step5_fixture_response + patch_draft_copy_for_asset.
    """
    base_event = {
        "name": "Argentina vs France",
        "home_team": "Argentina",
        "away_team": "France",
        "location": None,
        "start_date": "2026-05-27T19:00:00Z",
        "final_score": "3-2",
        "outcome_type": "upset_victory",
        "timeliness": 0.87,
        "ingested_at": "2026-05-27T19:30:00Z",
        # build_event_context writes this mid-pipeline; the mock doesn't persist writes,
        # so the draft node reads it back from here (precondition: narrative present).
        "event_narrative": build_valid_event_narrative().model_dump(mode="json"),
    }

    def find_events(args: dict) -> list:
        f = args.get("filter", {})
        event_id_filter = f.get("event_id")
        if isinstance(event_id_filter, str):
            return [{**base_event, "event_id": event_id_filter}]
        return []

    players = [
        {
            "player_id": "p1",
            "name": "Lionel Messi",
            "nationality": "Argentina",
            "team": "Argentina",
            "position": "Forward",
            "notable_facts": ["5th World Cup appearance", "2022 World Cup winner"],
            "career_milestones": "8x Ballon d'Or",
            "commercial_signal": "high",
        }
    ]

    mock_client.register("find", "events", find_events)
    mock_client.register("find", "player_context", players)
    mock_client.register("aggregate", "performance", [])
    # Downstream nodes: assets reads (ingested for similarity/scoring; scored for
    # drafts) + empty vector-search neighbors (valid → discovery, D-015).
    mock_client.register("find", "assets", _make_step6_assets_find_handler())
    mock_client.register_vector_search("assets", [])


async def _run_agent(runner, prompt: str = OPERATOR_PROMPT) -> tuple[list, Exception | None]:
    """Run the agent with the given prompt; return (events, run_error).

    Partial traces stay useful for a–f, but we no longer swallow the exception:
    the completion assertion surfaces it (named) so a pipeline abort can't pass
    silently. run_error is None on a clean run.
    """
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id="eval_user"
    )
    msg = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )
    events: list = []
    run_error: Exception | None = None
    try:
        async for event in runner.run_async(
            user_id="eval_user",
            session_id=session.id,
            new_message=msg,
        ):
            events.append(event)
    except Exception as exc:
        run_error = exc  # surfaced by _assert_pipeline_completed, not swallowed
    return events, run_error


def _assert_pipeline_completed(
    all_parts: list[dict], run_error: Exception | None, trace_path: str
) -> list[str]:
    """Forcing function: the smoke ran the whole graph to completion.

    A missing run_event_pipeline tool_response means the pipeline aborted (a node
    raised — almost always an unseeded read). We surface the captured exception so
    a future node added without extending _seed_mock_for_full_pipeline fails loudly
    and names itself, instead of passing on a partial trace.
    """
    pipeline_responses = [
        p for p in all_parts
        if p["kind"] == "tool_response" and p["name"] == "run_event_pipeline"
    ]
    if pipeline_responses:
        return []
    msg = "(g) run_event_pipeline never returned — pipeline aborted before completion."
    if run_error is not None:
        msg += (
            f" Aborted with {type(run_error).__name__}: {run_error}. "
            f"A node read state no handler seeds — extend _seed_mock_for_full_pipeline."
        )
    return [f"{msg} Trace: {trace_path}"]


def _assert_single_run(
    events: list, mock_client, trace_label: str, run_error: Exception | None = None
) -> list[str]:
    """Run all assertions. Returns list of failure messages (empty = pass)."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)

    tool_calls = extract_tool_calls(events)
    pipeline_calls = [c for c in tool_calls if c["name"] == "run_event_pipeline"]

    all_parts = _collect_parts(events)

    # (a) capability selection — coordinator dispatched the pipeline exactly once
    if len(pipeline_calls) != 1:
        failures.append(
            f"(a) Expected run_event_pipeline called 1 time, got {len(pipeline_calls)}. "
            f"Trace: {trace_path}"
        )

    # (b) natural-language field extraction — event_metadata passed to the pipeline
    if pipeline_calls:
        meta = pipeline_calls[0]["args"].get("event_metadata", {})
        if not isinstance(meta, dict):
            failures.append(f"(b) event_metadata is not a dict: {meta!r}. Trace: {trace_path}")
        else:
            teams = {meta.get("home_team"), meta.get("away_team")}
            if teams != {"Argentina", "France"}:
                failures.append(
                    f"(b) teams should be {{'Argentina', 'France'}}, "
                    f"got home={meta.get('home_team')!r} away={meta.get('away_team')!r}. "
                    f"Trace: {trace_path}"
                )
            score = str(meta.get("final_score", ""))
            if "3" not in score or "2" not in score:
                failures.append(
                    f"(b) final_score should contain '3' and '2', got {score!r}. "
                    f"Trace: {trace_path}"
                )
            if meta.get("outcome_type") != "upset_victory":
                failures.append(
                    f"(b) outcome_type: expected 'upset_victory', got {meta.get('outcome_type')!r}. "
                    f"Trace: {trace_path}"
                )
            start_date = str(meta.get("start_date", ""))
            if "19:00" not in start_date or ("Z" not in start_date and "+00:00" not in start_date):
                failures.append(
                    f"(b) start_date should be ISO 8601 UTC at 19:00, got {start_date!r}. "
                    f"Trace: {trace_path}"
                )

    # (c) MongoDB writes — one insert-many on events, one on assets
    db_events_calls = [
        (tn, args) for tn, args in mock_client.calls
        if tn == "insert-many" and args.get("collection") == "events"
    ]
    db_assets_calls = [
        (tn, args) for tn, args in mock_client.calls
        if tn == "insert-many" and args.get("collection") == "assets"
    ]
    if len(db_events_calls) != 1:
        failures.append(
            f"(c) Expected 1 insert-many on events, got {len(db_events_calls)}. "
            f"Trace: {trace_path}"
        )
    if len(db_assets_calls) != 1:
        failures.append(
            f"(c) Expected 1 insert-many on assets, got {len(db_assets_calls)}. "
            f"Trace: {trace_path}"
        )

    # (d) timeliness is a float in [0.0, 1.0] on the event document
    if db_events_calls:
        docs = db_events_calls[0][1].get("documents", [])
        if not docs:
            failures.append(f"(d) No documents in events insert-many. Trace: {trace_path}")
        else:
            tl = docs[0].get("timeliness")
            if not isinstance(tl, (int, float)) or not (0.0 <= float(tl) <= 1.0):
                failures.append(
                    f"(d) timeliness should be float in [0,1], got {tl!r}. "
                    f"Trace: {trace_path}"
                )

    # (e) reasoning text appears before the tool call
    first_tool_idx = next(
        (i for i, p in enumerate(all_parts) if p["kind"] == "tool_call"), None
    )
    text_before_tool = any(
        p["kind"] == "text" and i < (first_tool_idx if first_tool_idx is not None else len(all_parts))
        for i, p in enumerate(all_parts)
    )
    if not text_before_tool:
        failures.append(
            f"(e) No reasoning text before tool call — CoT directive may not be firing. "
            f"Trace: {trace_path}"
        )

    # (f) coordinator closed the loop: non-empty text after run_event_pipeline returns.
    # NOT is_final — per coordinator_system.md the coordinator presents the pipeline
    # result and then advances to request_human_approval (suspends), so the smoke's
    # natural terminus is an HITL suspension, not a final-text turn. What matters is
    # that the coordinator presented results rather than silently dying or calling a
    # non-existent tool.
    pipeline_response_idx = next(
        (i for i, p in enumerate(all_parts)
         if p["kind"] == "tool_response" and p["name"] == "run_event_pipeline"),
        None,
    )
    presented_text = any(
        p["kind"] == "text" and (p.get("text") or "").strip()
        and pipeline_response_idx is not None and i > pipeline_response_idx
        for i, p in enumerate(all_parts)
    )
    if not presented_text:
        failures.append(
            f"(f) No text after run_event_pipeline returned — coordinator did not present "
            f"the pipeline result. Trace: {trace_path}"
        )

    # (g) the pipeline ran end-to-end (forcing function against seed rot)
    failures.extend(_assert_pipeline_completed(all_parts, run_error, trace_path))

    return failures


@pytest.mark.anyio
async def test_step_1_single_run():
    """Single-run coordinator e2e smoke: NL → run_event_pipeline → full graph."""
    with build_runner_with_step6_mock() as (runner, mock_client):
        _seed_mock_for_full_pipeline(mock_client)
        with _stub_internal_llms(mock_client):
            events, run_error = await _run_agent(runner)

    failures = _assert_single_run(events, mock_client, "step_1_single_run", run_error)
    assert not failures, "\n".join(failures)


@pytest.mark.anyio
async def test_step_1_pass_rate():
    """Pass-rate eval: ≥95% of N runs must satisfy all assertions (D-020)."""
    n = int(os.environ.get("EVAL_REPEAT", "5"))
    passes = 0
    run_failures: list[tuple[int, list[str]]] = []

    for i in range(n):
        with build_runner_with_step6_mock() as (runner, mock_client):
            _seed_mock_for_full_pipeline(mock_client)
            with _stub_internal_llms(mock_client):
                events, run_error = await _run_agent(runner)
        failures = _assert_single_run(events, mock_client, f"step_1_pass_rate_run_{i}", run_error)
        if not failures:
            passes += 1
        else:
            run_failures.append((i, failures))

    required = math.ceil(n * 0.95)
    if passes < required:
        report_lines = [
            f"Pass rate {passes}/{n} ({100 * passes / n:.0f}%) is below the 95% threshold "
            f"({required}/{n} required).",
            "",
            "Failed runs:",
        ]
        for run_idx, msgs in run_failures:
            report_lines.append(f"  Run {run_idx}:")
            for msg in msgs:
                report_lines.append(f"    - {msg}")
        assert False, "\n".join(report_lines)


# ---------------------------------------------------------------------------
# Dir-path variant: coordinator must call list_images before run_event_pipeline
# (coordinator_system.md §34 — "If the operator gave a directory path, call
#  list_images first to enumerate the batch")
# ---------------------------------------------------------------------------


def _assert_dir_path_run(
    events: list, mock_client, trace_label: str, run_error: Exception | None = None
) -> list[str]:
    """Assertions for the directory-path ingest sequence. Returns failure messages."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)

    tool_calls = extract_tool_calls(events)
    all_parts = _collect_parts(events)

    list_calls = [c for c in tool_calls if c["name"] == "list_images"]
    pipeline_calls = [c for c in tool_calls if c["name"] == "run_event_pipeline"]

    # (a) list_images called exactly once
    if len(list_calls) != 1:
        failures.append(
            f"(a) Expected list_images called once, got {len(list_calls)}. "
            f"Trace: {trace_path}"
        )

    # (b) run_event_pipeline called exactly once
    if len(pipeline_calls) != 1:
        failures.append(
            f"(b) Expected run_event_pipeline called once, got {len(pipeline_calls)}. "
            f"Trace: {trace_path}"
        )

    # (c) list_images called before run_event_pipeline (sequencing)
    list_indices = [i for i, p in enumerate(all_parts) if p["kind"] == "tool_call" and p["name"] == "list_images"]
    pipeline_indices = [i for i, p in enumerate(all_parts) if p["kind"] == "tool_call" and p["name"] == "run_event_pipeline"]
    if list_indices and pipeline_indices:
        if list_indices[0] >= pipeline_indices[0]:
            failures.append(
                f"(c) list_images (part {list_indices[0]}) must precede run_event_pipeline "
                f"(part {pipeline_indices[0]}). Trace: {trace_path}"
            )
    elif not list_indices and pipeline_indices:
        failures.append(f"(c) run_event_pipeline called without a preceding list_images call. Trace: {trace_path}")

    # (d) run_event_pipeline images is a list of individual file paths, not the raw dir
    if pipeline_calls:
        imgs = pipeline_calls[0]["args"].get("images", [])
        if not isinstance(imgs, list) or not imgs:
            failures.append(
                f"(d) run_event_pipeline images should be a non-empty list, got {imgs!r}. "
                f"Trace: {trace_path}"
            )
        else:
            for img in imgs:
                if not any(img.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                    failures.append(
                        f"(d) images contains non-image entry {img!r} — coordinator may have "
                        f"passed the directory path directly instead of the files list. "
                        f"Trace: {trace_path}"
                    )
                    break

    # (e) MongoDB writes — events insert-many and assets insert-many each called once
    db_events = [(t, a) for t, a in mock_client.calls if t == "insert-many" and a.get("collection") == "events"]
    db_assets = [(t, a) for t, a in mock_client.calls if t == "insert-many" and a.get("collection") == "assets"]
    if len(db_events) != 1:
        failures.append(f"(e) Expected 1 insert-many on events, got {len(db_events)}. Trace: {trace_path}")
    if len(db_assets) != 1:
        failures.append(f"(e) Expected 1 insert-many on assets, got {len(db_assets)}. Trace: {trace_path}")

    # (f) reasoning text before first tool call (CoT directive)
    first_tool_idx = next((i for i, p in enumerate(all_parts) if p["kind"] == "tool_call"), None)
    text_before_tool = any(
        p["kind"] == "text" and i < (first_tool_idx if first_tool_idx is not None else len(all_parts))
        for i, p in enumerate(all_parts)
    )
    if not text_before_tool:
        failures.append(f"(f) No reasoning text before first tool call. Trace: {trace_path}")

    # (g) the pipeline ran end-to-end (forcing function against seed rot)
    failures.extend(_assert_pipeline_completed(all_parts, run_error, trace_path))

    return failures


@pytest.mark.anyio
async def test_step_1_dir_path_single_run():
    """Coordinator calls list_images when given a directory path, then run_event_pipeline.

    Patches src.agent._list_images_impl so no real filesystem access is needed.
    The coordinator must recognise the directory path, enumerate it via list_images,
    and pass the returned files list — not the raw path — to run_event_pipeline.
    """
    with build_runner_with_step6_mock() as (runner, mock_client):
        _seed_mock_for_full_pipeline(mock_client)
        with patch("src.agent._list_images_impl", return_value=_FAKE_LIST_IMAGES_RESULT), \
                _stub_internal_llms(mock_client):
            events, run_error = await _run_agent(runner, DIR_PATH_OPERATOR_PROMPT)

    failures = _assert_dir_path_run(events, mock_client, "step_1_dir_path_single_run", run_error)
    assert not failures, "\n".join(failures)
