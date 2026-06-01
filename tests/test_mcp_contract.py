"""Contract tests: replay captured *real* MCP envelopes through the parser.

Hermetic (no server, every run) but reality-derived — the fixtures in
tests/fixtures/mcp/ are recorded from the live mongodb-mcp-server by
scripts/capture_mcp_fixtures.py. They guard _parse_docs_response against the real
envelope shape, where the security preamble and footer reference the
<untrusted-user-data-...> tags inline (the case the mocks originally missed).

Re-capture (re-run the script) when MONGODB_MCP_VERSION changes; the live
test in test_live_smoke.py verifies the fixtures still match reality.
"""

import json
from pathlib import Path

from src.db import _parse_docs_response

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mcp"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


def test_find_nonempty_parses():
    docs = _parse_docs_response(_load("find_nonempty"))
    assert docs, "captured non-empty find parsed to nothing"
    assert all(isinstance(d, dict) and "asset_id" in d for d in docs)


def test_aggregate_vectorsearch_parses():
    docs = _parse_docs_response(_load("aggregate_vectorsearch"))
    assert docs and all("similarity" in d for d in docs)


def test_find_empty_returns_empty_list():
    assert _parse_docs_response(_load("find_empty")) == []


def test_real_envelope_is_the_hard_case():
    # The data block is NOT the first tag occurrence — the preamble and footer also
    # reference the tags, which is exactly what broke the non-greedy parser. If a
    # re-capture ever loses this shape, the fixture stops guarding the bug, so assert
    # the hard case is present.
    text = "".join(p.get("text", "") for p in _load("find_nonempty")["content"])
    assert text.count("<untrusted-user-data-") >= 3
