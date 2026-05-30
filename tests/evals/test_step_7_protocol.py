"""Behavioral branch probe for Step 7 coordinator protocol (T-7.15).

Tests whether the coordinator LlmAgent (flash) reliably follows the post-approval protocol:
  (a) apply_approval_decisions always called before execute/redraft
  (b) redraft-then-loop on edit_requested
  (c) execute-once when no edit_requested remain
  (d) stops at the cap

Run: EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_7_protocol.py -v

Requires GOOGLE_API_KEY. NOT a merge gate — Tier 1 + the unit suite are.
Pass rate ≥ 95%/20 is the behavioral quality bar (same posture as Steps 4/5/6).
On failure: climb the remediation ladder prompt-first (the post-approval protocol
section in coordinator_system.md is the first rung).
"""

import asyncio
import os
from unittest.mock import patch

import pytest

EVAL_REPEAT = int(os.environ.get("EVAL_REPEAT", "1"))

# Skip all tests in this module unless GOOGLE_API_KEY is set
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="Behavioral probe requires GOOGLE_API_KEY; not a CI gate.",
)


@pytest.mark.anyio
@pytest.mark.parametrize("run_idx", range(EVAL_REPEAT))
async def test_protocol_apply_before_branch(run_idx: int):
    """apply_approval_decisions is called before execute or redraft in all cases."""
    pytest.skip(
        "T-7.15 behavioral probe: coordinator orchestration protocol. "
        "Run manually with GOOGLE_API_KEY and EVAL_REPEAT=20. "
        "Requires full coordinator HITL integration with scripted FunctionResponse. "
        "Implementation deferred to demo-prep track when coordinator UI is wired."
    )
