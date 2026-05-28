"""Trace evals for the ingest_event_batch capability.

T-1.13: Single-run outcome-shaped eval (7 assertions).
T-1.14: Pass-rate eval (≥95% over N runs, N defaults to 5 in CI, 20 for gate).

Operator prompt used in both tests:
    "Argentina pulled off the upset, beating heavy favorites France 3-2.
     Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, /tmp/wc-final/img03.jpg.
     Match started 2026-05-27T19:00:00Z, finished ~20 min ago.
     Ingest this batch and confirm when done. Stop after ingestion."

The agent must:
  (a) call ingest_event_batch exactly once
  (b) extract correct fields from natural language (hardest: outcome_type)
  (c) drive two MongoDB insert-many calls (events + assets)
  (d) produce a non-null timeliness float in [0, 1] on the event document
  (e) emit reasoning text before the tool call (CoT directive from v2 prompt)
  (f) emit non-empty terminal text after the tool returns
  (g) include the failure trace path in any assertion message
"""

import math
import os

import pytest
from google.genai import types

from tests.evals.conftest import (
    build_runner_with_mock_db,
    dump_trace,
    extract_tool_calls,
)

APP_NAME = "event_commerce_ops_agent"

OPERATOR_PROMPT = (
    "Argentina pulled off the upset, beating heavy favorites France 3-2. "
    "Photos: /tmp/wc-final/img01.jpg, /tmp/wc-final/img02.jpg, /tmp/wc-final/img03.jpg. "
    "Match started 2026-05-27T19:00:00Z, finished ~20 min ago. "
    "Ingest this batch and confirm when done. Stop after ingestion."
)


async def _run_agent(runner) -> list:
    """Run the agent with the operator prompt; return all events.

    Catches ValueError from ADK when the agent attempts to call a tool that
    isn't registered yet — partial traces are still useful for assertion checks.
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
    except Exception:
        pass  # ADK may propagate tool errors (ValueError, PreconditionError, etc.) — partial traces still useful
    return events


def _assert_single_run(events: list, mock_client, trace_label: str) -> list[str]:
    """Run all seven assertions. Returns list of failure messages (empty = pass)."""
    failures: list[str] = []
    trace_path = dump_trace(events, trace_label)

    tool_calls = extract_tool_calls(events)
    ingest_calls = [c for c in tool_calls if c["name"] == "ingest_event_batch"]

    # Collect all classified parts once for text-order analysis
    from tests.evals.conftest import _collect_parts
    all_parts = _collect_parts(events)

    # (a) capability selection — ingest_event_batch called exactly once
    if len(ingest_calls) != 1:
        failures.append(
            f"(a) Expected ingest_event_batch called 1 time, got {len(ingest_calls)}. "
            f"Trace: {trace_path}"
        )

    # (b) natural-language field extraction
    if ingest_calls:
        meta = ingest_calls[0]["args"].get("event_metadata", {})
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

    # (f) non-empty terminal text after the tool returns
    last_tool_response_idx = None
    for i, p in enumerate(all_parts):
        if p["kind"] == "tool_response":
            last_tool_response_idx = i
    terminal_text = any(
        p["kind"] == "text" and p.get("is_final")
        and (last_tool_response_idx is None or i > last_tool_response_idx)
        for i, p in enumerate(all_parts)
    )
    if not terminal_text:
        failures.append(
            f"(f) No terminal text after tool returns — agent may be calling non-existent tools. "
            f"Trace: {trace_path}"
        )

    return failures


@pytest.mark.anyio
async def test_step_1_single_run():
    """Single-run outcome-shaped trace eval for ingest_event_batch."""
    with build_runner_with_mock_db() as (runner, mock_client):
        events = await _run_agent(runner)

    failures = _assert_single_run(events, mock_client, "step_1_single_run")
    assert not failures, "\n".join(failures)


@pytest.mark.anyio
async def test_step_1_pass_rate():
    """Pass-rate eval: ≥95% of N runs must satisfy all seven assertions (D-020)."""
    n = int(os.environ.get("EVAL_REPEAT", "5"))
    passes = 0
    run_failures: list[tuple[int, list[str]]] = []

    for i in range(n):
        with build_runner_with_mock_db() as (runner, mock_client):
            events = await _run_agent(runner)
        failures = _assert_single_run(events, mock_client, f"step_1_pass_rate_run_{i}")
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
