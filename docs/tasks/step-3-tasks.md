# Step 3 — Find Similar Assets: Task List

> Tasks T-3.1 through T-3.17 implement the `find_similar_assets` capability per `docs/plans/step-3-similarity.md`. One workflow `FunctionNode` (not a coordinator-facing tool — D-024) composing a `gemini-embedding-2` image embedding (via `google.genai` SDK), persistent storage of embeddings, an Atlas `$vectorSearch` query against the historical assets corpus, and persistence of the resulting neighbor lists. Four new internal Python wrappers in `src/db/assets.py`, one new private embedding helper in the capability module, two new Pydantic models, one new provisioning script, one seed-pipeline extension. Tasks follow the plan's § Dependency order verbatim.

Prerequisites:
- Step 2 merged to `main` (30/30 non-eval tests + N=20 trace eval pass rate ≥ 95% per CLAUDE.md § Current Phase).
- Branch `step/3-similarity` is rebased onto the new `main` (post-D-024).
- Branch housekeeping commit landed on `step/3-similarity` (doc-only, no code):
  - `docs/specs/02-architecture.md` updated — `assets` schema includes `similar_assets: list[str] | null`; new "Atlas Vector Search indexes" subsection defines `assets_embedding_index` (path `embedding`, dimensions `3072`, similarity `cosine`); MCP call list under `find_similar_assets` shows the explicit `$vectorSearch` pipeline shape.
  - `docs/plans/db-wrapper-inventory.md` — `vector_search_assets` row updated to signature `vector_search_assets(embedding, top_k=5, exclude_event_id=None)` with rationale (drops `channel`, adds `exclude_event_id`, lowers default `top_k`).
  - `tracking.md` — new D-entry capturing Step 3 architectural choices: similarity metric `cosine`, default `top_k=5`, setup-time vector index provisioning, `google.genai` + `GOOGLE_API_KEY` as the embedding auth path (reconciles D-006's "Vertex AI" framing — same model, different SDK surface), current-event assets get embedded (feedback-loop seed).
- `MongoMCPClient` + `get_client()` lazy singleton unchanged. `PreconditionError` from `src/errors.py` reused (no new error type this step).
- D-024 workflow scaffolding from Step 1/2 in place: `src/agent.py` `build_coordinator()` + `build_workflow()`, `src/capabilities/__init__.py` `build_pipeline_graph()` with chain `(START, ingest_event_batch_node, build_event_context_node)`, `run_event_pipeline` coordinator shim, eval scaffolding's `_MockMCPClient` with collection-keyed dispatch.

Design decisions baked in (see `docs/plans/step-3-similarity.md` § Decisions taken for rationale):
- The capability is a `FunctionNode` in the workflow graph — **not** a coordinator-facing `FunctionTool`. The agent's tool surface remains `run_event_pipeline` (unchanged from Step 2).
- Four new internal Python wrappers in `src/db/assets.py`: `get_assets_for_event`, `vector_search_assets`, `save_asset_embedding`, `save_similar_assets`. None exposed to the agent or coordinator.
- One private embedding helper `_compute_image_embedding` in `src/capabilities/similarity.py` wraps `google.genai`'s `embed_content` for `gemini-embedding-2`. Test seam for monkeypatching.
- `Asset.embedding` is permanent (idempotent skip on re-run); `Asset.similar_assets` is recomputable. Two distinct wrappers reflect lifecycle.
- `top_k=5`, `cosine` similarity, `assets_embedding_index` are the locked-in defaults. `numCandidates = 10 × top_k` (Atlas guidance for high-recall vector search).
- Vector index provisioned via one-time `scripts/setup_vector_index.py` — not at runtime.
- Seed pipeline (`scripts/seed_mongodb.py`) embeds historical assets eagerly. Fail-fast on unreachable image — surfaces provisioning problems immediately.
- Current event's assets get embedded (today's batch becomes tomorrow's corpus — feedback-loop seed).
- Trace eval starts from the same Argentina-vs-France operator prompt used in Step 2 (now with N images) and observes the coordinator + recorded MongoDB calls. Per Step 2's pattern, node firing is verified **indirectly** via the recorded call sequence on the mock client, not via direct workflow-node observation.

---

## T-3.1: Add `SimilarAsset` and `SimilarityResult` Pydantic models

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `SimilarAsset(BaseModel)` with `model_config = ConfigDict(extra="forbid")`. Fields: `asset_id: str`, `event_id: str`, `similarity: float = Field(..., ge=0.0, le=1.0)`, `product_route: str | None`, `scores: dict[str, Any] | None`.
- `SimilarityResult(BaseModel)`. Fields: `asset_id: str` (the current-event asset), `neighbors: list[SimilarAsset]`. No `extra="forbid"` constraint needed.
- Tests: happy-path construction, `similarity` field rejects values outside [0, 1], `neighbors=[]` accepted (empty-neighbors tolerance), `product_route=None` and `scores=None` accepted.

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k "similar_asset or similarity_result"`

---

## T-3.2: Add `Asset.similar_assets` field

Files: `src/models.py` (modify `Asset`), `tests/test_models.py` (extend)
Acceptance: `Asset.similar_assets: list[str] | None = None` (optional, defaults to `None`). Existing Asset tests continue to pass (additive + defaulted). New tests assert: (a) `Asset` constructs with `similar_assets=None`; (b) `Asset` constructs with `similar_assets=["asset-1", "asset-2"]`; (c) `Asset` rejects `similar_assets=[123]` (Pydantic enforces `list[str]`).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k asset`

---

## T-3.3: Extend conftest helpers

Files: `tests/conftest.py`
Acceptance: Two new helpers:
- `build_valid_similar_asset(**overrides) -> SimilarAsset` — returns a valid `SimilarAsset` instance with sensible defaults (`asset_id="past-asset-1"`, `event_id="evt-past-1"`, `similarity=0.85`, `product_route="poster"`, `scores={"quality_score": 0.9}`).
- `build_embedding_fixture() -> list[float]` — returns a deterministic 3072-element list of floats (e.g. `[0.1] * 3072`, or a small deterministic varying sequence) for use in unit + trace tests so embedding dimension assertions can be exercised without live API calls.

Both follow the same `**overrides` pattern as `build_valid_event`, `build_valid_asset`, `build_valid_player`.

Verify: `.venv/bin/python -c "from tests.conftest import build_valid_similar_asset, build_embedding_fixture; from src.models import SimilarAsset; sa = build_valid_similar_asset(); assert isinstance(sa, SimilarAsset); emb = build_embedding_fixture(); assert isinstance(emb, list) and len(emb) == 3072; print('ok')"`

---

## T-3.4: Implement `get_assets_for_event` wrapper

Files: `src/db/assets.py` (extend), `tests/test_step_3.py` (new file)
Acceptance: `get_assets_for_event(event_id: str, status: str | None = None) -> list[Asset]` is async; calls `get_client().call("find", {"database": "event_commerce", "collection": "assets", "filter": filter_dict})` where `filter_dict` is `{"event_id": event_id}` or `{"event_id": event_id, "status": status}` when `status` provided. Parses the MCP envelope using the pattern established by Step 2's `_parse_find_response` helper (whichever module owns it post-Step-2; if not promoted out, replicate the parse pattern with a matching one-line comment naming the source). Returns `list[Asset]` via `Asset.model_validate(doc)`, empty list when no matches.

Unit test monkeypatches `src.db.assets.get_client`; asserts (a) call args with and without `status` filter, (b) returns parsed `Asset` instances, (c) returns `[]` on empty result.

Verify: `.venv/bin/python -m pytest tests/test_step_3.py::test_get_assets_for_event -v`

---

## T-3.5: Implement `vector_search_assets` wrapper (LOAD-BEARING — the MongoDB partner-track integration)

Files: `src/db/assets.py` (extend), `tests/test_step_3.py` (extend)
Acceptance: `vector_search_assets(embedding: list[float], top_k: int = 5, exclude_event_id: str | None = None) -> list[SimilarAsset]` is async. Calls `get_client().call("aggregate", {"database": "event_commerce", "collection": "assets", "pipeline": [...]})`.

The pipeline must be exactly:

```python
NUM_CANDIDATES_MULTIPLIER = 10  # module-level constant in src/db/assets.py
INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME", "assets_embedding_index")

pipeline = [
    {
        "$vectorSearch": {
            "index": INDEX_NAME,
            "path": "embedding",
            "queryVector": embedding,
            "numCandidates": NUM_CANDIDATES_MULTIPLIER * top_k,
            "limit": top_k,
        }
    },
    # $match excluding the current event's own assets (only when exclude_event_id provided)
    *([{"$match": {"event_id": {"$ne": exclude_event_id}}}] if exclude_event_id else []),
    {
        "$project": {
            "_id": 0,
            "asset_id": 1,
            "event_id": 1,
            "product_route": 1,
            "scores": 1,
            "similarity": {"$meta": "vectorSearchScore"},
        }
    },
]
```

Returns `list[SimilarAsset]` via `SimilarAsset.model_validate(doc)` for each projected doc. Empty list when no matches (do not raise — empty-neighbor tolerance is the contract per the plan).

Unit tests:
- `test_vector_search_assets_pipeline_shape` — asserts the pipeline tuple exactly matches the expected shape with `top_k=5`, `exclude_event_id="evt-current"`, including `numCandidates=50` and the `$ne` filter.
- `test_vector_search_assets_without_exclude` — when `exclude_event_id=None`, pipeline omits the `$match` stage entirely.
- `test_vector_search_assets_index_env_override` — when `VECTOR_INDEX_NAME` env var is set, pipeline uses that name.
- `test_vector_search_assets_parses_envelope` — given a seeded envelope of projected docs, returns parsed `SimilarAsset` instances with `similarity` populated from the `$meta` projection.
- `test_vector_search_assets_empty_result` — when the envelope contains no docs, returns `[]`.

Verify: `.venv/bin/python -m pytest tests/test_step_3.py -v -k vector_search`

---

## T-3.6: Implement `save_asset_embedding` wrapper

Files: `src/db/assets.py` (extend), `tests/test_step_3.py` (extend)
Acceptance: `save_asset_embedding(asset_id: str, embedding: list[float]) -> None` is async. **Asserts `len(embedding) == 3072`** before the call — if not, raises `ValueError("embedding dimension mismatch: expected 3072, got <n>")` (catches the wrong-length-embedding risk at the persistence boundary per the plan's risks table). Then calls `get_client().call("update-many", {"database": "event_commerce", "collection": "assets", "filter": {"asset_id": asset_id}, "update": {"$set": {"embedding": embedding}}})`. No return value.

Unit tests:
- `test_save_asset_embedding_call_shape` — asserts MCP call args including the `$set.embedding` payload.
- `test_save_asset_embedding_rejects_wrong_dimension` — passing a 1024-element list raises `ValueError`; MCP client is never called.

Verify: `.venv/bin/python -m pytest tests/test_step_3.py -v -k save_asset_embedding`

---

## T-3.7: Implement `save_similar_assets` wrapper

Files: `src/db/assets.py` (extend), `tests/test_step_3.py` (extend)
Acceptance: `save_similar_assets(asset_id: str, similar_asset_ids: list[str]) -> None` is async. Calls `get_client().call("update-many", {"database": "event_commerce", "collection": "assets", "filter": {"asset_id": asset_id}, "update": {"$set": {"similar_assets": similar_asset_ids}}})`. No return value. Empty list is a valid input — write proceeds (an asset with no neighbors gets `similar_assets: []` persisted explicitly, distinguishing "no neighbors found" from "vector search not yet run").

Unit tests:
- `test_save_similar_assets_call_shape` — asserts call args with a non-empty list.
- `test_save_similar_assets_accepts_empty_list` — `similar_asset_ids=[]` proceeds; MCP call recorded.

Verify: `.venv/bin/python -m pytest tests/test_step_3.py -v -k save_similar_assets`

---

## T-3.8: Implement `_compute_image_embedding` helper

Files: `src/capabilities/similarity.py` (replace stub), `tests/test_step_3.py` (extend)
Acceptance: `_compute_image_embedding(image_url: str) -> list[float]` is async. Body:

- Reads `GOOGLE_API_KEY` (matches Step 2's path — `src/capabilities/context.py:22`).
- Reads `GEMINI_EMBEDDING_MODEL` (default `gemini-embedding-2`).
- Calls `genai.Client(api_key=...).models.embed_content(model=..., contents=<image input>, config=EmbedContentConfig(output_dimensionality=3072, task_type="RETRIEVAL_DOCUMENT"))`. The exact `contents` shape for image-modality input must be confirmed against the `google.genai` SDK docs at implementation time — likely `genai_types.Part.from_uri(uri=image_url, mime_type="image/jpeg")` or similar. Document the exact call shape with a one-line comment.
- Returns the embedding vector as `list[float]`. Asserts `len(result) == 3072` before returning (defense in depth — same assertion as T-3.6 catches it at the persistence layer; this catches it at the helper boundary for clearer error attribution).
- The `embed_content` SDK call is synchronous; if Step 3 capability is async, wrap via `asyncio.to_thread` at the call site (per Step 2 pattern with `_run_narrative_llm`). Private to module (underscore prefix) — test seam is monkeypatching `src.capabilities.similarity._compute_image_embedding`.

Unit tests:
- `test_compute_image_embedding_call_shape` — mocks `genai.Client` at the import boundary (`src.capabilities.similarity.genai.Client`); asserts the embed call passes `model="gemini-embedding-2"`, image input, and the 3072-dim config.
- `test_compute_image_embedding_returns_3072_dim` — mock returns a 3072-element list; helper returns it.
- `test_compute_image_embedding_rejects_wrong_dim` — mock returns a 1024-element list; helper raises `ValueError`.

Verify: `.venv/bin/python -m pytest tests/test_step_3.py -v -k compute_image_embedding`

---

## T-3.9: Implement `find_similar_assets` capability

Files: `src/capabilities/similarity.py` (replace stub), `tests/test_step_3.py` (extend)
Acceptance: `find_similar_assets(event_id: str) -> dict` is async. Behavior per `docs/plans/step-3-similarity.md` § "What the capability does internally":

```python
DEFAULT_TOP_K = 5  # module-level constant

async def find_similar_assets(event_id: str) -> dict:
    assets = await get_assets_for_event(event_id)
    if not assets:
        raise PreconditionError(
            capability="find_similar_assets",
            context=event_id,
            missing={"assets": "no assets for event; call ingest_event_batch first"},
        )

    # Embed-and-persist loop (idempotent — skip assets that already have an embedding)
    for asset in assets:
        if asset.embedding is None:
            embedding = await asyncio.to_thread(_compute_image_embedding, asset.content_url)
            await save_asset_embedding(asset.asset_id, embedding)
            asset.embedding = embedding

    # Search-and-persist loop
    similarity_results = []
    for asset in assets:
        neighbors = await vector_search_assets(
            embedding=asset.embedding,
            top_k=DEFAULT_TOP_K,
            exclude_event_id=event_id,
        )
        similarity_results.append({
            "asset_id": asset.asset_id,
            "neighbors": [n.model_dump(mode="json") for n in neighbors],
        })
        await save_similar_assets(asset.asset_id, [n.asset_id for n in neighbors])

    return {"event_id": event_id, "similar": similarity_results}
```

Capability docstring per `docs/plans/step-3-similarity.md` § "Tool docstring" — must name `gemini-embedding-2`, 3072-dim, cosine, the idempotent re-embed skip, the empty-neighbors-is-valid contract, and the downstream consumers (`propose_review_queue`, `draft_campaigns_for_queue`).

Unit tests cover:
- `test_find_similar_assets_raises_when_no_assets` — `get_assets_for_event` returns `[]` → `PreconditionError` with matching `capability`, `context`, `missing`.
- `test_find_similar_assets_full_orchestration` — three assets, none with embeddings; mocks all wrappers + `_compute_image_embedding`. Asserts: `_compute_image_embedding` invoked 3× (once per asset); `save_asset_embedding` invoked 3×; `vector_search_assets` invoked 3× (once per asset, with the asset's embedding); `save_similar_assets` invoked 3×; return dict has 3 entries in `similar` with correct shape.
- `test_find_similar_assets_idempotent_reembed_skip` — three assets, one with `embedding` already populated; asserts `_compute_image_embedding` invoked only 2×; `save_asset_embedding` invoked only 2×; vector search still invoked 3× (search runs for every asset regardless of embedding source).
- `test_find_similar_assets_empty_neighbors_tolerance` — `vector_search_assets` returns `[]` for one of the assets; capability completes without exception; `save_similar_assets` invoked with `similar_asset_ids=[]` for that asset; the corresponding `SimilarityResult` has `neighbors=[]`.
- `test_find_similar_assets_call_order` — uses ordered MagicMock assertions to verify the embed-loop completes for all assets before the search-loop begins (per the plan's "embed batch → search batch" sequencing).

Each unit test monkeypatches per-module bindings (`src.db.assets.get_client`) and `src.capabilities.similarity._compute_image_embedding`.

Verify: `.venv/bin/python -m pytest tests/test_step_3.py -v -k find_similar_assets`

---

## T-3.10: Add workflow adapter, FunctionNode, and graph edge

Files: `src/capabilities/__init__.py` (modify), `tests/test_step_3.py` (extend)
Acceptance:

1. **Adapter:** `_node_find_similar_assets(ctx, event_id: str) -> dict` matching the Step 1/2 pattern (`_node_ingest_event_batch`, `_node_build_event_context`). Body:
   ```python
   result = await _find_similar_assets(event_id)
   ctx.state["similarity_results"] = result["similar"]
   return result
   ```
   `event_id` is sourced from `ctx.state` via `parameter_binding="state"` (written by the upstream `ingest` node per Step 1).

2. **FunctionNode:** `find_similar_assets_node = FunctionNode(func=_node_find_similar_assets, name="find_similar_assets", parameter_binding="state")` at module level.

3. **Graph edge:** Extend `build_pipeline_graph()` from `[(START, ingest_event_batch_node, build_event_context_node)]` to `[(START, ingest_event_batch_node, build_event_context_node, find_similar_assets_node)]`.
   - **Verify ADK Workflow edge semantics first.** The current Step 1/2 form is a single chain-tuple. If ADK v2.1's `Workflow` rejects 4-element chain-tuples, fall back to pairwise: `[(START, ingest_event_batch_node), (ingest_event_batch_node, build_event_context_node), (build_event_context_node, find_similar_assets_node)]`. Document which form the API accepts in a one-line comment.

4. **Update module docstring:** The existing docstring lists `Step 3 → adds find_similar_assets node` as a future extension — remove that future-tense bullet and replace with a present-tense description in the doc body.

Integration smoke test (in `tests/test_step_3.py`):
- `test_workflow_includes_similarity_node` — imports `build_workflow()` from `src.agent`, calls it, asserts the workflow has three nodes by name (`ingest_event_batch`, `build_event_context`, `find_similar_assets`).

Verify:
- `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); w = build_workflow(); print('ok')"`
- `.venv/bin/python -m pytest tests/test_step_3.py::test_workflow_includes_similarity_node -v`

---

## T-3.11: Vector index provisioning script

Files: `scripts/setup_vector_index.py` (new)
Acceptance: One-time idempotent script that creates the Atlas Vector Search index `assets_embedding_index` against the `assets` collection. Path = `embedding`, dimensions = 3072, similarity = `cosine`, type = `vectorSearch`.

Implementation approach: call the MongoDB MCP `atlas-*` family or the Atlas Admin API directly (whichever is exposed via the MCP server's introspection — check at implementation time). On startup, check whether the index already exists; no-op if so, create if not. Print a clear status line: `index 'assets_embedding_index' created` or `index 'assets_embedding_index' already exists`. Atlas index creation is asynchronous (~minutes); the script may either return immediately after submitting the create request or poll until READY — pick poll-until-READY so the operator running the script has a clear "done" signal (timeout 10 minutes).

CLI: `.venv/bin/python scripts/setup_vector_index.py` (no args required; reads `MONGODB_URI` and Atlas credentials from env).

Verification is operational, not unit-tested (it's a provisioning script). After running once on the demo Atlas cluster, the index appears in the Atlas console and `db.assets.getSearchIndexes()` returns it.

Verify (operational, not in the per-PR gate): `.venv/bin/python scripts/setup_vector_index.py` — exits 0; rerun exits 0 with "already exists" message.

---

## T-3.12: Extend seed pipeline with embedding pass

Files: `scripts/seed_mongodb.py` (modify)
Acceptance:
1. After seeding historical assets, the script computes `_compute_image_embedding(asset.content_url)` for each seeded asset and writes the embedding inline with the insert (or via a post-insert `save_asset_embedding` call — whichever is cleaner given the current seed structure).
2. New CLI flag `--vector-only` re-embeds the existing corpus without re-seeding. Behavior: for every asset in `assets`, if `embedding is None`, compute and persist; if already populated, skip. Useful for iteration during Step 3 development.
3. **Fail-fast on unreachable image** (per the human-gate decision). If `_compute_image_embedding` raises (e.g. image URL not reachable), the seed aborts immediately with a clear error message naming the failing `asset_id` and `content_url`. Do not catch and continue.

Verify (operational):
- Fresh seed: `.venv/bin/python scripts/seed_mongodb.py` — completes; every seeded asset has a 3072-dim `embedding`.
- Re-embed: `.venv/bin/python scripts/seed_mongodb.py --vector-only` — no-ops if all assets already have embeddings; populates any missing ones.
- Fail-fast: introducing a bogus `content_url` on one seeded asset causes the seed to abort with the asset_id in the error message.

(Out-of-band: the existing Step 0 conftest patches the MongoDB MCP client, so this task does **not** add new unit tests for the seed script — its correctness is operational.)

---

## T-3.13: Extend eval scaffolding for `$vectorSearch` dispatch and embedding patch

Files: `tests/evals/conftest.py` (modify), `tests/evals/test_mock_dispatch.py` (extend)
Acceptance:

1. **`_MockMCPClient` dispatch extension** — when an `aggregate` call's pipeline starts with `$vectorSearch`, route to a seeded fixture rather than the existing collection-keyed dispatch. New registration API:
   ```python
   mock_client.register_vector_search(
       collection="assets",
       results=[<seeded list of projected docs matching SimilarAsset shape>],
   )
   ```
   Implementation: extend the dispatch table with a `(tool_name, collection, "$vectorSearch")` key. The dispatch checks `pipeline[0]` for the `$vectorSearch` stage before falling back to collection-keyed dispatch.

2. **Embedding-helper patch surface** — eval harness must monkeypatch `src.capabilities.similarity._compute_image_embedding` to return `build_embedding_fixture()` rather than hitting live Gemini. Add this patch into `build_runner_with_mock_db()` so trace evals are insulated from Vertex AI by default. Tests that want to exercise the real helper opt in explicitly.

3. **Envelope shape:** the mock continues to return the standard MCP envelope `{"content": [{"type": "text", "text": <json>}]}`; for `$vectorSearch` results, `<json>` is the JSON-encoded projected-doc list.

4. Smoke test extensions in `tests/evals/test_mock_dispatch.py`:
   - `test_mock_dispatch_vector_search` — registers a `$vectorSearch` fixture; invokes `vector_search_assets` directly with the mock; asserts returned `SimilarAsset` list matches the fixture.
   - `test_mock_dispatch_falls_back_to_collection_key` — without a vector-search registration, an `aggregate` on `performance` still dispatches via the collection key (Step 2 behavior unchanged).
   - `test_embedding_helper_is_patched_in_runner` — instantiates a runner via `build_runner_with_mock_db()`, asserts `src.capabilities.similarity._compute_image_embedding` is a mock that returns `build_embedding_fixture()`.

Verify: `.venv/bin/python -m pytest tests/evals/test_mock_dispatch.py -v`

---

## T-3.14: Write outcome-shaped trace eval (single run)

Files: `tests/evals/test_step_3_trace.py` (new)
Acceptance: Reuses the Step 2 Argentina-vs-France operator prompt (with 3 images for testing across multiple assets). Pre-seeded state in the mock:
- The Step 2 seeded event + past events + player_context + performance aggregate.
- A vector-search fixture of 5 historical `SimilarAsset`s per asset (so top-K returns are non-empty for at least 2 of the 3 ingested assets; 1 asset gets an empty-neighbors fixture to exercise the discovery-queue path).
- The `_compute_image_embedding` patch returns `build_embedding_fixture()` (3072-dim deterministic).

Test asserts nine outcomes per `docs/plans/step-3-similarity.md` § Verification checkpoints (trace-eval row):

(a) **Coordinator dispatch** — coordinator called `run_event_pipeline` exactly once.
(b) **outcome_type extraction preserved** — `event_metadata.outcome_type == "upset_victory"` (Step 2 regression guard).
(c) **Embedding helper invocation count** — `_compute_image_embedding` mock invoked once per ingested asset (3 times total).
(d) **Embedding persistence** — mock client `.calls` includes one `update-many` on `assets` per ingested asset setting `embedding` (length 3072). Three such calls.
(e) **Vector search shape** — mock client `.calls` includes one `aggregate` on `assets` per ingested asset whose pipeline starts with `$vectorSearch` carrying `index="assets_embedding_index"`, `path="embedding"`, `numCandidates >= 10 * top_k`, `limit == top_k`, and (if `exclude_event_id` is wired) a `$match` excluding the current event. Three such calls.
(f) **Similar-assets persistence** — mock client `.calls` includes one `update-many` on `assets` per ingested asset setting `similar_assets`. Three such calls. The asset with the empty-neighbors fixture has `similar_assets=[]` persisted (not skipped).
(g) **Call order across nodes** — recorded `.calls` index order shows the ingest writes (events + assets inserts) before the context reads/writes before the similarity writes. Establishes that the workflow chain advanced correctly without observing nodes directly.
(h) **CoT directive still firing** — at least one `text` event-part appears before the dispatch tool call (carries forward from Step 2).
(i) **No live API calls** — `_compute_image_embedding` patch was actually used (assertable by checking the mock's call count, not just absence of network errors).

On any assertion failure: `dump_trace()` writes the full trace under `tests/evals/_failures/step_3_trace_<timestamp>.json` and the path is included in the failure message.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_3_trace.py::test_step_3_single_run -v`

---

## T-3.15: Write pass-rate trace eval (N=20)

Files: `tests/evals/test_step_3_trace.py` (extend)
Acceptance: A second test function runs the single-run eval N=20 times (configurable via `EVAL_REPEAT`, default 5 in CI). Asserts ≥ 19/20 runs pass all nine assertions (95% threshold per D-020). On failure, prints per-assertion pass rate and which assertion failed in which run.

Step 3 has **no LLM-generated content inside the capability** — embeddings are deterministic modulo provider-side floating-point variance, MongoDB calls are deterministic, neighbor fixtures are deterministic. The expected pass rate is 20/20. If runs flake, the failure is almost certainly in the **coordinator's dispatch path** (the coordinator's flash LLM occasionally fails to extract `outcome_type` or to dispatch `run_event_pipeline` — Step 2 regression surface). If pass-rate dips below threshold, follow the remediation playbook per `docs/plans/evaluation-strategy.md`: tighten coordinator prompt → tighten capability docstring (so the workflow node's contract is clearer if the coordinator ever introspects it) → tighten `run_event_pipeline` shim's metadata-extraction prompt → swap `GEMINI_COORDINATOR_MODEL` to a stronger model as the last rung.

The MVP-acceptability escape hatch is explicitly forbidden by CLAUDE.md and the user's standing feedback memory — climb the ladder fully before declaring done.

Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_3_trace.py::test_step_3_pass_rate -v`

---

## T-3.16: Document new env vars in README

Files: `README.md` (modify — locate the existing env-vars section established by Step 1/2)
Acceptance: Two new env vars documented:
- `GEMINI_EMBEDDING_MODEL` (default `gemini-embedding-2`) — model id for image embeddings in `find_similar_assets`. Independent of `GEMINI_MODEL` (workflow nodes' chat model) and `GEMINI_COORDINATOR_MODEL` (coordinator chat model).
- `VECTOR_INDEX_NAME` (default `assets_embedding_index`) — Atlas Vector Search index name. Keeps the index name out of code so eval and live can use different indexes.

Also confirm the README documents `GOOGLE_API_KEY` (used by Step 2's narrative LLM AND now Step 3's embedding helper — same auth path) and `MONGODB_URI` + `MDB_MCP_API_CLIENT_ID` / `MDB_MCP_API_CLIENT_SECRET` for the MongoDB MCP server.

(No `.env.example` exists in the repo — match existing convention.)

Verify: `grep -q "GEMINI_EMBEDDING_MODEL" README.md && grep -q "VECTOR_INDEX_NAME" README.md && echo "ok"`

---

## T-3.17: Full suite green

Files: (no new files)
Acceptance: All tests in `tests/` (including `tests/evals/`) pass with no errors. Then run the pass-rate gate (`EVAL_REPEAT=20`) — must hit ≥ 19/20 on `test_step_3_pass_rate` AND the existing `test_step_2_pass_rate` regression (Step 3's changes must not regress Step 2's gate).

**Approximate total after Step 3: ~50 passing tests.** (Step 2 finished at ~30 non-eval tests; Step 3 adds ~20 across model + wrapper + capability + workflow-integration + mock-dispatch + trace evals.)

Verify:
- `.venv/bin/python -m pytest tests/ -v` — full unit + single-run evals green (no regressions on Step 1/2 tests).
- `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_2_trace.py::test_step_2_pass_rate tests/evals/test_step_3_trace.py::test_step_3_pass_rate -v` — both gates pass.
- `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` — shells still build.

---

## Tracking note

If trace eval pass-rate dips below the 95% threshold, follow the remediation ladder in `docs/plans/evaluation-strategy.md` § Remediation. Step 3 has no LLM inside the capability — the flake surface is the **coordinator's dispatch decision** and `event_metadata` extraction (Step 2 regression surface). Cheap rungs (coordinator prompt tightening → capability docstring tightening → run_event_pipeline shim metadata-extraction prompt) must be tried before the model swap (`GEMINI_COORDINATOR_MODEL` → stronger model). Per CLAUDE.md and the standing feedback rule, "acceptable for MVP" is not a valid stopping point with cheaper rungs untried.

Step 3's trace eval exercises failure categories **1, 3, 5** per `docs/plans/evaluation-strategy.md`: tool selection (a — coordinator dispatched correctly; g — workflow advanced through similarity), tool arguments (b, e — the vector-search pipeline shape, the right index, the right top-K), end-state (c, d, f — embeddings persisted, neighbors persisted, similarity_results populated in state). Category 4 (tool-output handling — hallucination) is downgraded — no LLM inside the capability means no hallucination surface. Category 6 (strategy coherence) does not apply until `propose_review_queue` ships in Step 5.

Per `docs/plans/workflow.md` Phase 6, advisor consultation is required before declaring Step 3 done — independent read on whether the implementation matches the plan, whether the eval exercises what it claims to (especially the call-order assertion (g) — easy to write a passing eval that doesn't actually exercise the chain), and whether anything was quietly cut to make tests pass. Commit before the advisor call so the deliverable is durable if the session ends mid-call.
