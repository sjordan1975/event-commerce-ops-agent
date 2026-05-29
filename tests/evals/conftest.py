"""Shared eval helpers reused across all capability trace evals.

Mock strategy: patch src.db.events.get_client, src.db.assets.get_client,
src.db.performance.get_client, and src.db.player_context.get_client (the bound
names in each wrapper module) rather than src.db.get_client, since the wrappers
bind the name at import time via `from src.db import get_client`.
"""

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Union
from unittest.mock import patch

from src.agent import APP_NAME, build_coordinator, build_runner
from src.models import AssetScores, GeneratedCopy
from tests.conftest import build_embedding_fixture, build_valid_generated_copy, build_valid_vision_scoring_output


def _make_mcp_envelope(docs: list[dict]) -> dict:
    """Encode a list of docs as a real MongoDB MCP find/aggregate envelope."""
    if not docs:
        return {"content": [{"type": "text", "text": "Query resulted in 0 documents."}]}
    uid = "mock-uuid-eval"
    data_text = (
        f"Query resulted in {len(docs)} documents.\n\n"
        f"<untrusted-user-data-{uid}>\n"
        f"{json.dumps(docs)}\n"
        f"</untrusted-user-data-{uid}>\n"
        f"Use the information above to respond."
    )
    return {
        "content": [
            {"type": "text", "text": f"Query resulted in {len(docs)} documents."},
            {"type": "text", "text": data_text},
        ]
    }


class _MockMCPClient:
    """Records all (tool_name, args) invocations; dispatches reads from a table.

    Dispatch table keyed by (tool_name, collection). Values are either a static
    list/dict or a callable(args) -> list/dict for cases that need to inspect
    the filter (e.g., two different find calls on the same collection).

    For aggregate calls whose pipeline starts with $vectorSearch, dispatch is
    keyed by (tool_name, collection, "$vectorSearch") — checked before the
    plain collection-keyed fallback. Register via register_vector_search().

    Write operations (insert-many, update-many) that have no handler registered
    return {"content": [{"type": "text", "text": "ok"}]} (response not parsed
    by any wrapper).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._handlers: dict[tuple, Union[list, dict, Callable]] = {}

    def register(
        self,
        tool_name: str,
        collection: str,
        handler: Union[list, dict, Callable],
    ) -> None:
        """Register a static result or callable handler for (tool_name, collection)."""
        self._handlers[(tool_name, collection)] = handler

    def register_vector_search(
        self,
        collection: str,
        results: list[dict],
    ) -> None:
        """Register a fixture for $vectorSearch aggregates on the given collection."""
        self._handlers[("aggregate", collection, "$vectorSearch")] = results

    async def call(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        collection = args.get("collection", "")

        # $vectorSearch dispatch: check pipeline[0] before falling back to collection key
        if tool_name == "aggregate":
            pipeline = args.get("pipeline", [])
            if pipeline and "$vectorSearch" in pipeline[0]:
                vs_key = ("aggregate", collection, "$vectorSearch")
                if vs_key in self._handlers:
                    handler = self._handlers[vs_key]
                    result = handler(args) if callable(handler) else handler
                    return _make_mcp_envelope(result)

        key = (tool_name, collection)
        if key in self._handlers:
            handler = self._handlers[key]
            result = handler(args) if callable(handler) else handler
            return _make_mcp_envelope(result)
        return {"content": [{"type": "text", "text": "ok"}]}


def _default_vision_fixture_provider(image_url: str, event_context: dict):
    """Default Vision helper stub: populates detected_subjects from key_figure_names.

    Splits the comma-joined key_figure_names string into individual names so
    the hallucination-guard assertion in T-4.13 passes by construction.
    Pass a custom fixture_provider to build_runner_with_mock_db() to override.

    Note: save_asset_scores calls update-many on the assets collection.
    The _MockMCPClient default "ok" handler covers this write — no explicit
    dispatch handler is required for scoring writes.
    """
    key_figure_names = event_context.get("key_figure_names", "(none)")
    if key_figure_names == "(none)":
        subjects = []
    else:
        subjects = [n.strip() for n in key_figure_names.split(", ") if n.strip()]
    return build_valid_vision_scoring_output(detected_subjects=subjects)


@contextmanager
def build_runner_with_mock_db(vision_fixture_provider=None):
    """Context manager that yields (runner, mock_client) with MongoDB patched out.

    Patches all four db module get_client bindings, patches
    src.capabilities.similarity._compute_image_embedding to return a
    deterministic 3072-dim fixture, and patches
    src.capabilities.scoring._score_asset_with_vision to return a deterministic
    VisionScoringOutput — no live Gemini calls during trace evals.

    vision_fixture_provider: callable(image_url, event_context) -> VisionScoringOutput.
    Defaults to _default_vision_fixture_provider (splits key_figure_names).
    """
    if vision_fixture_provider is None:
        vision_fixture_provider = _default_vision_fixture_provider

    mock_client = _MockMCPClient()
    with (
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch("src.db.player_context.get_client", return_value=mock_client),
        patch(
            "src.capabilities.similarity._compute_image_embedding",
            return_value=build_embedding_fixture(),
        ),
        patch(
            "src.capabilities.scoring._score_asset_with_vision",
            side_effect=vision_fixture_provider,
        ),
    ):
        agent = build_coordinator()
        runner = build_runner(agent)
        yield runner, mock_client


def classify_part(part) -> dict:
    """Return a dict describing what kind of content this ADK part carries.

    Mirrors the pattern from spike/adk_event_capture.py (D-020 mechanism).
    """
    text = getattr(part, "text", None)
    if text:
        return {"kind": "text", "text": text}

    fc = getattr(part, "function_call", None)
    if fc is not None:
        return {
            "kind": "tool_call",
            "name": getattr(fc, "name", None),
            "args": dict(fc.args) if getattr(fc, "args", None) else {},
        }

    fr = getattr(part, "function_response", None)
    if fr is not None:
        return {
            "kind": "tool_response",
            "name": getattr(fr, "name", None),
            "response": dict(fr.response) if getattr(fr, "response", None) else {},
        }

    return {"kind": "unknown", "repr": repr(part)}


def _collect_parts(events: list) -> list[dict]:
    parts = []
    for event in events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            classified = classify_part(part)
            classified["author"] = event.author
            classified["is_final"] = event.is_final_response()
            parts.append(classified)
    return parts


def extract_tool_calls(events: list) -> list[dict]:
    """Return all tool_call parts from the event stream."""
    return [p for p in _collect_parts(events) if p["kind"] == "tool_call"]


def extract_tool_responses(events: list) -> list[dict]:
    """Return all tool_response parts from the event stream."""
    return [p for p in _collect_parts(events) if p["kind"] == "tool_response"]


def dump_trace(events: list, label: str) -> str:
    """Serialize event stream to tests/evals/_failures/{label}.json; return path."""
    failures_dir = Path(__file__).parent / "_failures"
    failures_dir.mkdir(exist_ok=True)
    path = failures_dir / f"{label}.json"
    path.write_text(
        json.dumps(_collect_parts(events), indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)


# ---------------------------------------------------------------------------
# Step 5 eval scaffolding (T-5.12)
# ---------------------------------------------------------------------------

# Cutoff used by Step 5 (default; must match QUEUE_EXPLOITATION_SIMILARITY_CUTOFF)
_STEP5_CUTOFF = 0.75

# The four Step-5 assets: ast-0 (exploitation identity), ast-1 (exploitation),
# ast-2 (worth-it discovery), ast-3 (not-worth discovery).
_STEP5_ASSET_IDS = ["ast-0", "ast-1", "ast-2", "ast-3"]

# Inferred routes for exploitation assets (mechanical, D-015)
_STEP5_INFERRED_ROUTES = {
    "ast-0": "poster",
    "ast-1": "tshirt",
}

# Which assets land in which pool after prepare (determined by vector search fixture)
STEP5_EXPLOITATION_IDS = {"ast-0", "ast-1"}
STEP5_DISCOVERY_IDS = {"ast-2", "ast-3"}


def _make_step5_assets_find_handler() -> Callable:
    """Return a handler that produces 4 assets for the Step-5 seeded event.

    Handles two filter shapes:
    - no status → 4 ingested assets (used by Steps 3/4/5)
    - status='scored' → same 4 assets with scored status + no queue assignments
      (valid-degenerate: Step 6 sees no surfaced assets and returns empty lists)
    """
    _base_scores = {
        "quality_score": 0.7, "merch_score": 0.7, "emotional_score": 0.7,
        "social_score": 0.7, "identity_score": 0.7,
    }

    def handler(args: dict) -> list:
        f = args.get("filter", {})
        event_id = f.get("event_id")
        if not event_id:
            return []
        status = f.get("status")
        if status is None:
            return [
                {
                    "asset_id": f"ast-{i}",
                    "event_id": event_id,
                    "content_url": f"/tmp/wc-final/img0{i+1}.jpg",
                    "status": "ingested",
                    "upload_date": datetime.now(timezone.utc).isoformat(),
                    "product_route": None,
                    "queue_type": None,
                    "queue_rank": None,
                    "queue_rationale": None,
                    "embedding": None,
                    "scores": None,
                    "detected_subjects": None,
                    "campaign_id": None,
                    "similar_assets": None,
                }
                for i in range(4)
            ]
        if status == "scored":
            # Step 6 reads scored assets — return 4 scored assets with no queue assignments
            # so draft_campaigns_for_queue takes the valid-degenerate empty path.
            return [
                {
                    "asset_id": f"ast-{i}",
                    "event_id": event_id,
                    "content_url": f"/tmp/wc-final/img0{i+1}.jpg",
                    "status": "scored",
                    "upload_date": datetime.now(timezone.utc).isoformat(),
                    "product_route": None,
                    "queue_type": None,
                    "queue_rank": None,
                    "queue_rationale": None,
                    "embedding": None,
                    "scores": _base_scores,
                    "detected_subjects": [],
                    "campaign_id": None,
                    "similar_assets": None,
                }
                for i in range(4)
            ]
        return []
    return handler


def _make_step5_vector_search_handler() -> Callable:
    """Return a handler that gives ast-0/ast-1 strong neighbors, ast-2 weak, ast-3 empty.

    Call order matches the per-asset loop in find_similar_assets (assets processed
    in DB-insertion order, which matches the 4-asset fixture).
    """
    call_count: dict[str, int] = {"n": 0}

    def handler(args: dict) -> list:
        n = call_count["n"]
        call_count["n"] += 1
        if n == 0:
            # ast-0: strong match → exploitation (poster, identity)
            return [{"asset_id": "past-0", "event_id": "evt-past-1",
                     "similarity": 0.91, "product_route": "poster", "scores": None}]
        elif n == 1:
            # ast-1: strong match → exploitation (tshirt)
            return [{"asset_id": "past-1", "event_id": "evt-past-1",
                     "similarity": 0.82, "product_route": "tshirt", "scores": None}]
        elif n == 2:
            # ast-2: weak match → discovery (high emotional, worth it)
            return [{"asset_id": "past-2", "event_id": "evt-past-1",
                     "similarity": 0.31, "product_route": None, "scores": None}]
        else:
            # ast-3: no match → discovery (low scores, not worth it)
            return []
    return handler


def _step5_vision_provider(image_url: str, event_context: dict) -> Any:
    """Per-asset differentiated Vision scores for Step 5 seeded fixture.

    ast-0 (img01): high quality + identity match (Messi) — exploitation leader
    ast-1 (img02): high merch — exploitation follow
    ast-2 (img03): high emotional + Messi candid — worth-it discovery
    ast-3 (img04): low scores — not worth surfacing
    """
    if "img01" in image_url:
        return build_valid_vision_scoring_output(
            scores=AssetScores(
                quality_score=0.9, merch_score=0.8, emotional_score=0.7,
                social_score=0.8, identity_score=0.95,
            ),
            detected_subjects=["Lionel Messi"],
        )
    elif "img02" in image_url:
        return build_valid_vision_scoring_output(
            scores=AssetScores(
                quality_score=0.8, merch_score=0.85, emotional_score=0.6,
                social_score=0.7, identity_score=0.3,
            ),
            detected_subjects=[],
        )
    elif "img03" in image_url:
        return build_valid_vision_scoring_output(
            scores=AssetScores(
                quality_score=0.85, merch_score=0.4, emotional_score=0.92,
                social_score=0.75, identity_score=0.8,
            ),
            detected_subjects=["Lionel Messi"],
        )
    else:
        return build_valid_vision_scoring_output(
            scores=AssetScores(
                quality_score=0.35, merch_score=0.3, emotional_score=0.4,
                social_score=0.3, identity_score=0.2,
            ),
            detected_subjects=[],
        )


@contextmanager
def build_runner_with_step5_mock(narrative_fixture: dict):
    """Context manager for Step 5 evals: mock DB + embedding + vision with step-5-shaped data.

    Yields (runner, mock_client). The caller seeds mock_client with event / player /
    performance data before using it.
    """
    mock_client = _MockMCPClient()
    with (
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch("src.db.player_context.get_client", return_value=mock_client),
        patch(
            "src.capabilities.similarity._compute_image_embedding",
            return_value=build_embedding_fixture(),
        ),
        patch(
            "src.capabilities.scoring._score_asset_with_vision",
            side_effect=_step5_vision_provider,
        ),
    ):
        agent = build_coordinator()
        runner = build_runner(agent)
        yield runner, mock_client


@contextmanager
def step5_fixture_response(canned: dict):
    """Set/clear _FIXTURE_RESPONSE on the queue module (Tier-1 eval seam)."""
    import src.capabilities.queue as q_module
    old = q_module._FIXTURE_RESPONSE
    try:
        q_module._FIXTURE_RESPONSE = canned
        yield
    finally:
        q_module._FIXTURE_RESPONSE = old


async def run_with_transient_retry(coro_factory, max_retries: int = 1):
    """Run coro_factory() and retry once on transient API errors (5xx / rate-limit / timeout).

    Returns (events, excluded) where excluded=True means all attempts were transient
    failures (caller should exclude this run from the pass-rate denominator).
    Judgment-assertion failures are raised, not excluded.
    """
    _TRANSIENT_PATTERNS = (
        "503", "429", "quota", "rate limit", "timeout", "deadline",
        "ServiceUnavailable", "ResourceExhausted",
    )

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            events = await coro_factory()
            return events, False
        except Exception as exc:
            msg = str(exc)
            if any(p.lower() in msg.lower() for p in _TRANSIENT_PATTERNS):
                last_exc = exc
                continue
            raise
    # All attempts were transient failures — exclude this run
    return [], True


# ---------------------------------------------------------------------------
# Step 6 eval scaffolding (T-6.11)
# ---------------------------------------------------------------------------

# Asset IDs used in Step 6 pre-seeded scored corpus.
# ast-0: poster/exploitation — Messi in frame (identity match)
# ast-1: tshirt/exploitation — high merch, no identity
# ast-2: social_only/discovery — emotional moment with Messi
# ast-3: un-surfaced (queue_type=None) — should NOT get a campaign
# ast-4: social_only/discovery — crowd shot, empty detected_subjects (hallucination guard)
STEP6_ASSET_IDS = ["ast-0", "ast-1", "ast-2", "ast-3", "ast-4"]
STEP6_QUEUED_IDS = {"ast-0", "ast-1", "ast-2", "ast-4"}
STEP6_UNSURFACED_ID = "ast-3"
STEP6_CROWD_ASSET_ID = "ast-4"

# Canned GeneratedCopy returned by the Tier-1 mock for _draft_copy_for_asset.
_CANNED_COPY = build_valid_generated_copy()


def _make_step6_scored_assets(event_id: str) -> list[dict]:
    """Return the pre-seeded route-spanning scored assets for the Step 6 eval."""
    base_scores_hi = {"quality_score": 0.9, "merch_score": 0.8, "emotional_score": 0.7, "social_score": 0.8, "identity_score": 0.95}
    base_scores_merch = {"quality_score": 0.8, "merch_score": 0.85, "emotional_score": 0.6, "social_score": 0.7, "identity_score": 0.3}
    base_scores_emo = {"quality_score": 0.85, "merch_score": 0.4, "emotional_score": 0.92, "social_score": 0.75, "identity_score": 0.8}
    base_scores_lo = {"quality_score": 0.35, "merch_score": 0.3, "emotional_score": 0.4, "social_score": 0.3, "identity_score": 0.2}
    base_scores_crowd = {"quality_score": 0.75, "merch_score": 0.3, "emotional_score": 0.85, "social_score": 0.9, "identity_score": 0.1}
    return [
        {
            "asset_id": "ast-0", "event_id": event_id,
            "content_url": "/tmp/wc-final/img01.jpg",
            "status": "scored", "upload_date": "2026-06-01T21:00:00Z",
            "product_route": "poster",
            "queue_type": "exploitation", "queue_rank": 1,
            "queue_rationale": "Identity match: Messi in frame leads exploitation queue",
            "embedding": None, "scores": base_scores_hi,
            "detected_subjects": ["Lionel Messi"], "campaign_id": None, "similar_assets": None,
        },
        {
            "asset_id": "ast-1", "event_id": event_id,
            "content_url": "/tmp/wc-final/img02.jpg",
            "status": "scored", "upload_date": "2026-06-01T21:00:00Z",
            "product_route": "tshirt",
            "queue_type": "exploitation", "queue_rank": 2,
            "queue_rationale": "High merch score drives t-shirt route",
            "embedding": None, "scores": base_scores_merch,
            "detected_subjects": [], "campaign_id": None, "similar_assets": None,
        },
        {
            "asset_id": "ast-2", "event_id": event_id,
            "content_url": "/tmp/wc-final/img03.jpg",
            "status": "scored", "upload_date": "2026-06-01T21:00:00Z",
            "product_route": "social_only",
            "queue_type": "discovery", "queue_rank": 1,
            "queue_rationale": "Emotional moment captures fan energy",
            "embedding": None, "scores": base_scores_emo,
            "detected_subjects": ["Lionel Messi"], "campaign_id": None, "similar_assets": None,
        },
        {
            "asset_id": "ast-3", "event_id": event_id,
            "content_url": "/tmp/wc-final/img04.jpg",
            "status": "scored", "upload_date": "2026-06-01T21:00:00Z",
            "product_route": None,
            "queue_type": None, "queue_rank": None, "queue_rationale": None,
            "embedding": None, "scores": base_scores_lo,
            "detected_subjects": [], "campaign_id": None, "similar_assets": None,
        },
        {
            "asset_id": "ast-4", "event_id": event_id,
            "content_url": "/tmp/wc-final/img05.jpg",
            "status": "scored", "upload_date": "2026-06-01T21:00:00Z",
            "product_route": "social_only",
            "queue_type": "discovery", "queue_rank": 2,
            "queue_rationale": "Crowd shot captures collective emotion",
            "embedding": None, "scores": base_scores_crowd,
            "detected_subjects": [],  # crowd shot — hallucination guard probe
            "campaign_id": None, "similar_assets": None,
        },
    ]


def _make_step6_assets_find_handler() -> Callable:
    """Combined assets find handler for Step 6 evals.

    Branches by filter:
    - no status → Step 5 base corpus (4 ingested assets, for upstream scoring/similarity)
    - status='scored' → pre-seeded route-spanning queue-bearing assets (Step 6 reads this)
    """
    _step5_base = _make_step5_assets_find_handler()

    def handler(args: dict) -> list:
        f = args.get("filter", {})
        status = f.get("status")
        event_id = f.get("event_id", "evt-demo-1")

        if not status:
            return _step5_base(args)
        if status == "scored":
            return _make_step6_scored_assets(event_id)
        return []

    return handler


@contextmanager
def patch_draft_copy_for_asset(canned: GeneratedCopy | None = None):
    """Context manager: patch _draft_copy_for_asset to return canned copy (Tier 1).

    Pass canned=None (default) to leave _draft_copy_for_asset live (grounding probe).
    """
    if canned is None:
        yield
        return
    with patch("src.capabilities.drafts._draft_copy_for_asset", return_value=canned):
        yield


@contextmanager
def build_runner_with_step6_mock():
    """Context manager for Step 6 evals: Step 5 scaffolding + campaigns DB patch.

    Does NOT patch _draft_copy_for_asset — use patch_draft_copy_for_asset() for Tier 1.
    Yields (runner, mock_client). Caller seeds mock_client with event/player/
    performance/vector-search data; use _make_step6_assets_find_handler() for assets.
    """
    mock_client = _MockMCPClient()
    with (
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch("src.db.player_context.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch(
            "src.capabilities.similarity._compute_image_embedding",
            return_value=build_embedding_fixture(),
        ),
        patch(
            "src.capabilities.scoring._score_asset_with_vision",
            side_effect=_step5_vision_provider,
        ),
    ):
        agent = build_coordinator()
        runner = build_runner(agent)
        yield runner, mock_client
