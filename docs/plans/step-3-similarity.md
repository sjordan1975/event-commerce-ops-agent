# Step 3 — `find_similar_assets`: Implementation Plan

## Context

Step 3 delivers the `find_similar_assets` capability — for every asset ingested with the current event, it computes a `gemini-embedding-2` image embedding (Vertex AI, 3072-dim), persists the embedding, and runs MongoDB Atlas `$vectorSearch` against historical assets to retrieve the top-K most similar past performers. Results carry the past assets' `product_route` and `scores` forward, providing the per-channel signal that `propose_review_queue` (capability 5) composes with the narrative into the operator review queue.

This is **the primary load-bearing MongoDB integration** for the partner-track demo (D-001, D-006, D-019, D-021). The wrapper `vector_search_assets` must appear explicitly in the trace — burying it inside a higher-level capability would hide the integration the judges are looking for (D-021 § "Explicit similarity").

Step 3 is the **first purely-deterministic capability with a non-MongoDB external dependency** (Vertex AI embeddings). No LLM-shaped reasoning inside the capability — the agent's only judgment around similarity happens in Step 5 (`propose_review_queue`). This step lands as a `FunctionNode` in the D-024 workflow graph; the coordinator shell does not change.

Prerequisite: Step 2 (`build_event_context`) is merged to `main`. The workflow graph contains `START → ingest_event_batch → build_event_context`. Step 3 extends it.

---

## What this capability delivers

Workflow node `find_similar_assets` reads `event_id` from session state (written by `ingest_event_batch`). It then:

1. Loads the event's assets via `get_assets_for_event(event_id)`.
2. For each asset *without* an embedding: calls `compute_image_embedding(content_url)` → Vertex AI `gemini-embedding-2`, then persists via `save_asset_embedding(asset_id, embedding)`. Idempotent — assets that already carry an embedding are skipped (re-running the workflow does not re-embed).
3. For each asset: calls `vector_search_assets(embedding, top_k=K, exclude_event_id=event_id)` → top-K historical similar assets with similarity scores + their `product_route` + `scores`.
4. Persists the resulting neighbor lists via `save_similar_assets(asset_id, similar_asset_ids)` — analytical derivation.
5. Returns `{"event_id": str, "similar": list[SimilarityResult]}` where each `SimilarityResult` is one entry per current-event asset, carrying its ranked neighbors.

Writes `similarity_results` to session state for downstream nodes.

Consumed by:
- **`propose_review_queue` (capability 5)** — hard precondition. Queue assembly needs both `event_narrative` and similarity results to compose the exploitation queue. Refuses if absent.
- **`draft_campaigns_for_queue` (capability 6)** — reads the assets' persisted `similar_assets` field plus the past-asset `product_route` they imply.

---

## The capability surface (D-019 + D-021)

| Surface | Type | Notes |
| --- | --- | --- |
| `find_similar_assets_node` | `FunctionNode` (workflow graph) | New node added to `build_pipeline_graph()`. Edge: `build_event_context → find_similar_assets`. Reads `event_id` from state; writes `similarity_results`. |
| `_node_find_similar_assets` | adapter (`src/capabilities/__init__.py`) | Wraps `find_similar_assets()` and writes outputs back to `ctx.state`. Same pattern as `_node_ingest_event_batch` / `_node_build_event_context`. |
| `find_similar_assets` | capability function (`src/capabilities/similarity.py`) | The function body — replaces the existing stub. Internal to the workflow node. |

Internal Python wrappers added this step (none agent-facing; none registered as `FunctionTool`s):

| Wrapper | File | Purpose |
| --- | --- | --- |
| `get_assets_for_event(event_id, status=None)` | `src/db/assets.py` (extension) | Cross-cutting `find` utility, reused by Step 4 + Step 5. Returns `list[Asset]`. |
| `vector_search_assets(embedding, top_k=5, exclude_event_id=None)` | `src/db/assets.py` (extension) | The **load-bearing** MongoDB call. Wraps `assets aggregate` with a `$vectorSearch` stage on the `assets_embedding_index` (with `numCandidates = NUM_CANDIDATES_MULTIPLIER × top_k`, default multiplier 10) followed by `$match` to exclude the current event's own assets and a `$project` to surface (asset_id, event_id, product_route, scores, similarity score). Returns `list[SimilarAsset]`. **Signature deviation from `db-wrapper-inventory.md`:** the inventory entry is `vector_search_assets(embedding, top_k=20, channel=None)`. This plan drops `channel` (per-channel routing is Step 5's judgment, not Step 3's wrapper concern — neighbors' `product_route` is surfaced in the result for Step 5 to compose over) and adds `exclude_event_id` (prevents an event's own assets from being returned as their own neighbors). Default `top_k` lowered from 20 to 5 (see § Decisions taken). Inventory will be updated in branch housekeeping. |
| `save_asset_embedding(asset_id, embedding)` | `src/db/assets.py` (extension) | Permanent write — once set, never recomputed. |
| `save_similar_assets(asset_id, similar_asset_ids)` | `src/db/assets.py` (extension) | Analytical write — could be recomputed if the corpus grows. |

Plus non-MongoDB (internal to the capability):

| Helper | File | Purpose |
| --- | --- | --- |
| `compute_image_embedding(image_url)` | `src/capabilities/similarity.py` (private function `_compute_image_embedding`) | Wraps the `google.genai` SDK `embed_content` call for `gemini-embedding-2` with 3072-dim configuration and image-modality input. Testable via monkeypatch on `src.capabilities.similarity._compute_image_embedding`. |

**SDK / auth path:** Step 2 already uses `google.genai` with `GOOGLE_API_KEY` (Google AI Studio surface) — `src/capabilities/context.py:22` is `genai.Client(api_key=os.environ["GOOGLE_API_KEY"])`. Step 3 matches this pattern for consistency. D-006's "Vertex AI" framing is partially out of step with the codebase's actual auth path; reconciling that is a tracking-doc concern (new D-entry recommended), not a Step 3 implementation concern. The `google.genai` SDK supports both AI Studio (`api_key=`) and Vertex (`vertexai=True, project=…, location=…`); flipping later is a one-line client-construction change behind the helper.

Per D-019, `MongoMCPClient` remains the only MongoDB programmatic client; new wrappers call `get_client().call(...)` exactly like Step 1 and Step 2 wrappers. The regression test that the agent does not directly expose MCP continues to pass.

---

## What the LLM does in this capability

**Nothing inside the capability.** Step 3 is purely deterministic from the workflow's view — `gemini-embedding-2` is an embedding model, not a chat model, and produces a vector deterministically (modulo provider-side floating-point variance).

The agent's `run_event_pipeline` dispatch decision (the coordinator's only LLM call relevant to this capability) is unchanged from Step 1/2 — coordinator decides to invoke `run_event_pipeline`, the workflow executes deterministically, the result lands back in coordinator state.

Per `agentic-model.md`, Step 3 is in the **purely computational** band of the capability surface — it has no reasoning surface for the agent or for an internal LLM. The internal-LLM-call pattern set by Step 2 (`_run_narrative_llm`) is **not** instantiated here.

---

## What the capability does internally

```text
find_similar_assets(event_id: str) → dict
    1. assets = await get_assets_for_event(event_id)
         raises PreconditionError if event has no assets (call ingest_event_batch first)
    2. for asset in assets:
           if asset.embedding is None:
               embedding = await _compute_image_embedding(asset.content_url)
               await save_asset_embedding(asset.asset_id, embedding)
               asset.embedding = embedding   # keep local list in sync for step 3
    3. similarity_results = []
       for asset in assets:
           neighbors = await vector_search_assets(
               embedding=asset.embedding,
               top_k=K,
               exclude_event_id=event_id,
           )
           inferred_route = _infer_route_from_neighbors(neighbors)  # None if neighbors empty
           similarity_results.append({
               "asset_id": asset.asset_id,
               "neighbors": [n.model_dump() for n in neighbors],
               "inferred_route": inferred_route,
           })
           await save_similar_assets(asset.asset_id, [n.asset_id for n in neighbors])
    4. return {"event_id": event_id, "similar": similarity_results}
```

Step 1 (assets loaded) is the only hard precondition that raises. Steps 2–3 tolerate empty `neighbors` lists — a brand-new corpus or an asset with no historical analogue still returns a valid `SimilarityResult` with `neighbors: []`. The exploration/discovery queue in Step 5 specifically wants these no-match assets (D-015), so empty neighbors is a *feature*, not a failure.

Sequencing within the loop: embedding-compute-and-persist *for every asset* before *any* vector search begins. This is intentional — it means re-runs after a partial failure resume cheaply, and the trace shows a clean "embed batch → search batch" shape rather than interleaved calls. The cost is one extra pass over the list; negligible at MVP cardinality (≤20 assets per event).

---

## Pydantic models (new)

```python
class SimilarAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    event_id: str
    similarity: float = Field(..., ge=0.0, le=1.0)
    product_route: str | None
    scores: dict[str, Any] | None
```

Returned by `vector_search_assets`. The `similarity` score is the value MongoDB `$vectorSearch` puts on `$meta: "vectorSearchScore"` (cosine score, in [0, 1] for normalized embeddings).

```python
class SimilarityResult(BaseModel):
    asset_id: str                       # current event's asset
    neighbors: list[SimilarAsset]       # ranked top-K from history
    inferred_route: str | None          # mechanical inference from neighbors' product_route
                                        # plurality vote; similarity-weighted tie-break;
                                        # None when neighbors is empty (discovery candidate)
```

Returned per current-event asset from the capability. Capability result is `{event_id, similar: list[SimilarityResult].model_dump()}`.

**Routing inference (mechanical, not judgment):** per the spec and D-025, channel routing for the exploitation queue is implied by majority-channel of nearest neighbors — *not* a Step 5 judgment surface. Step 3 computes this as `inferred_route` on each `SimilarityResult` via a private helper `_infer_route_from_neighbors(neighbors) -> str | None`. Algorithm: plurality vote over `neighbors[].product_route`; ties broken by sum-of-similarity; returns `None` when `neighbors` is empty (the discovery-queue candidate path). Step 3 does **not** persist `inferred_route` to the asset — that write boundary belongs to Step 5's `assign_asset_to_queue(asset_id, queue_type, product_route, reasoning)` wrapper, so Step 5 can override the inference for exploration items or when Vision (Step 4) flags an asset as unprintable.

Model addition to existing `Asset`: append `similar_assets: list[str] | None = None`. (Currently the field is implied by the architecture spec but not on the Pydantic model.) Default `None` — populated by `save_similar_assets`.

---

## Persistence: `embedding` and `similar_assets` on `assets`

`Asset.embedding: list[float] | None` is already on the model. `Asset.similar_assets: list[str] | None` is added this step.

`embedding` is permanent (once computed, never recomputed). `similar_assets` is recomputable — if the corpus grows, the neighbor list could shift, so it's an analytical derivation rather than a permanent fact. Splitting the wrappers (`save_asset_embedding` + `save_similar_assets`) reflects the lifecycle difference per the wrapper inventory.

The persisted embedding is what makes *this event's assets* part of the corpus for the next event's vector search. This is the seed of the feedback loop — assets ingested today become tomorrow's similarity anchors.

---

## Atlas Vector Search index

The `$vectorSearch` aggregation stage requires an index. New provisioning task:

- **Index name:** `assets_embedding_index`
- **Field path:** `embedding`
- **Dimensions:** `3072` (matches `gemini-embedding-2` output)
- **Similarity metric:** `cosine`
- **Type:** `vectorSearch` (Atlas Search index, not a regular index)

Provisioned via a one-time setup script (`scripts/setup_vector_index.py` — new) that calls the Atlas Admin API or the MongoDB MCP `atlas-create-...` family. Run once after seeding; idempotent (no-op if already exists). The plan does **not** create the index inside the capability — that would be a runtime concern leaking into a wrapper, and the Atlas API for index creation is asynchronous (provisioning takes ~minutes), which is incompatible with a request-path wrapper.

`scripts/seed_mongodb.py` must be extended to compute and persist `embedding` for each seeded historical asset, so the corpus is searchable by the time the trace eval runs. This is a real change to the seed pipeline — see "Seed corpus" below.

---

## Seed corpus (load-bearing — without this, vector search returns nothing)

For Step 3's trace eval to exercise the real path, the historical `assets` corpus must contain assets with:
- a populated 3072-dim `embedding`
- a known `product_route` (so neighbors carry routing signal forward)
- populated `scores` (so downstream Step 5 has something to compose)

Extension to `scripts/seed_mongodb.py`:
1. After seeding the historical events, for each historical asset call `compute_image_embedding(content_url)` and write the embedding inline with the insert.
2. Add a CLI flag `--vector-only` that re-embeds the existing corpus without re-seeding, for iteration during Step 3 development.

The Step 3 plan **does not** introduce a new "synthetic performance" generator — D-015 + D-021 assume the seed corpus already carries scores and product_route (Step 0 seed pipeline contract). Step 3 only adds the embedding column to that existing seed.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `SimilarAsset`, `SimilarityResult` models | `src/models.py` (extension) | New Pydantic types for vector-search results |
| 2 | `Asset.similar_assets` field | `src/models.py` (modification) | New optional `list[str] \| None` field |
| 3 | `get_assets_for_event` wrapper | `src/db/assets.py` (extension) | Cross-cutting `find` utility |
| 4 | `vector_search_assets` wrapper | `src/db/assets.py` (extension) | Load-bearing `$vectorSearch` aggregate |
| 5 | `save_asset_embedding` wrapper | `src/db/assets.py` (extension) | Permanent embedding write |
| 6 | `save_similar_assets` wrapper | `src/db/assets.py` (extension) | Analytical neighbor-list write |
| 7 | `_compute_image_embedding` helper | `src/capabilities/similarity.py` | Vertex AI `gemini-embedding-2` call (image modality, 3072-dim) |
| 8 | `find_similar_assets` capability | `src/capabilities/similarity.py` (replaces stub) | Orchestrates load → embed-and-persist → search-and-persist loop |
| 9 | `_node_find_similar_assets` adapter | `src/capabilities/__init__.py` (modification) | Workflow adapter that writes `similarity_results` to state |
| 10 | `find_similar_assets_node` FunctionNode | `src/capabilities/__init__.py` (modification) | Module-level FunctionNode instance, `parameter_binding="state"` |
| 11 | `build_pipeline_graph` edge | `src/capabilities/__init__.py` (modification) | Extend the existing chain tuple from `(START, ingest, context)` to `(START, ingest, context, similarity)`. (ADK `Workflow.edges` accepts chain-tuples per the current Step 1/2 shape — confirm exact semantics against the ADK v2.1 `Workflow` docs at implementation time; if the API needs pairwise tuples instead, add `(context_node, similarity_node)` as a second edge entry.) |
| 12 | Vector-index provisioning script | `scripts/setup_vector_index.py` (new) | One-time idempotent Atlas vector-search index create |
| 13 | Seed extension | `scripts/seed_mongodb.py` (modification) | Compute + persist embeddings for historical assets at seed time; `--vector-only` flag for re-embedding |
| 14 | Conftest helpers | `tests/conftest.py` (extension) | `build_valid_similar_asset()`, `build_embedding_fixture()` (a deterministic 3072-dim vector for unit tests) |
| 15 | Tests — unit | `tests/test_step_3.py` (new), `tests/test_models.py` (extension) | Models; wrappers (mocked MCP envelope shapes including `$vectorSearch` aggregate); capability orchestration with mocked embedding helper and mocked client; idempotent re-embedding skip; empty-neighbor tolerance |
| 16 | Tests — trace eval | `tests/evals/test_step_3_trace.py` (new) | Outcome-shaped trace eval (single-run + N=20 repeat) — dispatches `run_event_pipeline` end-to-end with mocked embedding + mocked vector-search results |
| 17 | Eval conftest extension | `tests/evals/conftest.py` (modification) | Extend `_MockMCPClient` to dispatch the `$vectorSearch` aggregate; add embedding-helper patch surface so traces don't hit live Vertex AI |

---

## Dependency order

1. **Models** — `SimilarAsset`, `SimilarityResult`; modify `Asset` to add `similar_assets: list[str] | None = None`
2. **Conftest helpers** — `build_valid_similar_asset()`, `build_embedding_fixture()` (returns `[0.1] * 3072`-style deterministic vector)
3. **Wrappers** (`src/db/assets.py` extensions) — `get_assets_for_event`, `vector_search_assets`, `save_asset_embedding`, `save_similar_assets`; each unit-tested independently via monkeypatched client
4. **`_compute_image_embedding` helper** — unit-tested with a mocked Vertex AI client; verifies 3072-dim output shape, retry on transient error
5. **`find_similar_assets` capability** — composes load + embed-loop + search-loop + neighbor-persist; unit test mocks both `get_client` (per-module) and `_compute_image_embedding`; covers idempotent re-embed skip, empty-neighbor tolerance, precondition raise
6. **Workflow adapter + FunctionNode + graph edge** (`src/capabilities/__init__.py`) — `_node_find_similar_assets`, `find_similar_assets_node`, append to `build_pipeline_graph()` edge list
7. **Vector index provisioning script** (`scripts/setup_vector_index.py`) — idempotent create against Atlas; run manually as part of step setup
8. **Seed extension** (`scripts/seed_mongodb.py`) — compute + persist embeddings for historical assets; `--vector-only` flag
9. **Trace eval scaffolding extension** (`tests/evals/conftest.py`) — `_MockMCPClient` learns the `$vectorSearch` aggregate shape; embedding-helper patch surface
10. **Trace eval — single run** (`tests/evals/test_step_3_trace.py`) — outcome-shaped assertions per the verification table
11. **Trace eval — pass rate** — `EVAL_REPEAT=20`, ≥ 95% threshold per D-020

---

## "Tool docstring" (capability docstring — load-bearing for evals and capability legibility)

Even though the capability is a `FunctionNode` and not directly agent-facing in D-024, the docstring is still load-bearing — it documents the capability for future maintainers, downstream capability authors, and the trace eval's assertion logic.

```python
async def find_similar_assets(event_id: str) -> dict:
    """Finds past assets visually/semantically similar to those in this event.

    For every asset on the event, computes a gemini-embedding-2 image embedding
    (Vertex AI, 3072-dim, cosine), persists it to assets.embedding (idempotent —
    skipped if already present), then runs Atlas $vectorSearch against the
    historical assets corpus (excluding this event's own assets) for top-K
    neighbors. Persists neighbor asset_ids to assets.similar_assets.

    Returns {"event_id": str, "similar": list[SimilarityResult]} where each
    SimilarityResult is {asset_id, neighbors: list[SimilarAsset]} carrying
    similarity score + product_route + scores forward from the past asset.

    Empty neighbors lists are valid — an asset with no historical analogue is
    a candidate for the discovery queue (D-015, D-021); the capability does not
    treat this as failure.

    Raises PreconditionError if the event has no assets (call ingest_event_batch
    first).

    Consumed by propose_review_queue (required precondition for queue assembly)
    and draft_campaigns_for_queue (reads asset.similar_assets + neighbors'
    product_route)."""
```

---

## System prompt context

`prompts/v3/coordinator_system.md` does **not** need to change for Step 3. The coordinator's job is unchanged — it still dispatches `run_event_pipeline`, and the workflow extends underneath it transparently. The coordinator does not "see" individual capabilities; it sees one dispatch tool and a returned result.

If the trace eval surfaces a coordinator-side issue (e.g. coordinator fails to dispatch when similarity context is mentioned in chat), apply the remediation ladder — but do not pre-emptively edit. **Confirmed: no prompt change required in Step 3.**

---

## Risks

| Risk | Mitigation |
| --- | --- |
| Vertex AI `gemini-embedding-2` is unavailable or rate-limits during trace eval (20× reps × ≤20 assets per event = up to 400 API calls per gate run) | Eval mocks `_compute_image_embedding` via the patch surface in `tests/evals/conftest.py` — returns deterministic 3072-dim vectors. Live API only exercised in seed and in a separate `tests/test_vertex_smoke.py` (out-of-band, not in the per-PR gate). |
| Atlas vector-search index is not provisioned when eval runs | `tests/evals/conftest.py` mocks the `$vectorSearch` aggregate response shape directly; trace eval does not require a real index. Live index is required only for end-to-end demo, validated by a separate `scripts/verify_vector_index.py` health check. |
| Embedding dimension mismatch between gemini-embedding-2 actual output and the index definition | Wrapper asserts `len(embedding) == 3072` before write; if a future Vertex AI default shifts, the assertion surfaces it at the persistence boundary rather than at search time. |
| `$vectorSearch` envelope shape varies between MongoDB MCP versions | Wrapper parses the envelope shape (`{"content": [{"text": "..."}]}` per existing client.py) and validates against `SimilarAsset` Pydantic schema. If structure shifts, validation surfaces a clear error. |
| Seeded corpus has no embeddings → vector search returns empty for every asset → trace eval can't distinguish "no match" from "search broken" | Trace eval asserts the **mock client recorded the `$vectorSearch` call with the expected `numCandidates`, `limit`, and `index` parameters**. Mock returns a seeded fixture of neighbors. The live-corpus case (where embeddings really might be sparse early in operation) is a Step 5 / demo-narrative concern, not a Step 3 correctness concern. |
| Idempotent re-embed skip silently masks a corrupted embedding | The "skip if embedding is not None" branch checks for `None` only — a list of wrong length or a list of all zeros still flows through. Wrapper-level length assertion catches the wrong-length case at insert time. All-zero is unlikely from gemini-embedding-2 in practice; not guarding for it. |
| The mock-DB call-shape discrimination for `$vectorSearch` becomes fragile | Extend `_MockMCPClient` with a dispatch entry keyed on `(tool_name, pipeline[0].keys())` — when the pipeline starts with `$vectorSearch`, route to the vector-search fixture; otherwise existing per-collection dispatch. Keeps the extension surgical. |
| Top-K is configurable but the default is arbitrary | Default `K=5` for MVP. Single configuration constant `DEFAULT_TOP_K = 5` in `src/capabilities/similarity.py`; tunable later without spreading magic numbers. |
| The `exclude_event_id` filter accidentally excludes too much (e.g. excludes valid neighbors that share an event_id by coincidence in fixtures) | `exclude_event_id` matches on `event_id` field equality only — historical assets have distinct event_ids by construction (events are immutable). Tested explicitly in unit tests. |
| Cosine on a multimodal embedding may not preserve **subject identity** as the dominant similarity signal. `gemini-embedding-2` encodes identity *and* scene *and* composition *and* mood, all mixed. Top-K for a "Messi celebration" shot could return five generic celebration shots rather than five Messi shots, losing the identity signal that's actually load-bearing for merch routing. | Not fixed at the Step 3 layer — Step 3 stays purely "embed + vector search, no judgment." The mitigation lands downstream: **Step 4 (Vision scoring) extracts identity as structured fields** (e.g. `detected_subjects`, `recognizable_jersey`); **Step 5 (propose_review_queue) composes identity + similarity + narrative `key_figures`** when assembling the exploitation queue, upweighting identity-matched neighbors over generic-scene matches. Flagged here so Step 5 planning inherits the constraint rather than discovering it organically. |
| Vertex AI image-modality embedding requires the image to be reachable (HTTP/GCS URL) | All seeded asset `content_url`s are GCS URIs reachable by the seeded service account; demo `images` parameter to the workflow accepts the same. Out-of-band: a separate task validates GCS reachability before the demo. |

**Hallucination is not a Step 3 risk** — there is no LLM in the capability. The categorical equivalent is **embedding mis-routing** (an embedding that gets compared against the wrong index field, returning nonsense neighbors). The wrapper-level dimension assertion + the index-field-path being literal-string-bound in the aggregate pipeline both protect against this.

---

## Env vars required

| Var | Purpose | Default |
| --- | --- | --- |
| `GOOGLE_API_KEY` | Existing — `google.genai` SDK (now also used for `gemini-embedding-2`) | None — required |
| `GEMINI_EMBEDDING_MODEL` | Model id for embedding generation | `gemini-embedding-2` |
| `MONGODB_URI` / `MDB_MCP_*` | Existing — MongoDB MCP connection | (existing) |
| `VECTOR_INDEX_NAME` | Atlas vector-search index name | `assets_embedding_index` |

`GEMINI_EMBEDDING_MODEL` is new but follows the existing pattern (`GEMINI_MODEL`, `GEMINI_COORDINATOR_MODEL`, `GEMINI_NARRATIVE_MODEL`). `VECTOR_INDEX_NAME` is new — keeps the index name out of code so eval and live can use different indexes if needed.

Document the new vars in the README env section (no `.env.example` exists in the repo today — match existing project convention rather than adding one).

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v` | `SimilarAsset` and `SimilarityResult` validate happy-path and reject malformed; `Asset.similar_assets` accepts None and `list[str]`; existing model tests still pass. |
| Wrappers (unit) | `.venv/bin/python -m pytest tests/test_step_3.py -v -k wrapper` | `get_assets_for_event`, `vector_search_assets`, `save_asset_embedding`, `save_similar_assets` each call mocked client with correct `(database, collection, filter/pipeline)` shape. `vector_search_assets` must pass `index=assets_embedding_index`, `path="embedding"`, `numCandidates`/`limit` derived from `top_k`, and `$match` excluding `event_id`. Envelope parsing converts text payloads to `SimilarAsset` lists. |
| `_compute_image_embedding` helper (unit) | `.venv/bin/python -m pytest tests/test_step_3.py -v -k embedding` | Calls mocked Vertex AI client with model id `gemini-embedding-2`, image modality, returns 3072-element float list; wrapper-level assertion on output dimension. |
| Capability orchestration (unit) | `.venv/bin/python -m pytest tests/test_step_3.py -v -k capability` | `find_similar_assets` raises `PreconditionError` when event has no assets; idempotent re-embed skip works (asset with existing embedding is not re-embedded); empty-neighbors tolerance (no exception on zero matches); calls in order: load → embed-loop → search-loop → return; mocked `_compute_image_embedding` invoked once per missing-embedding asset; `vector_search_assets` invoked once per asset; `save_similar_assets` invoked once per asset. |
| Workflow integration (unit) | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Both shells build cleanly; workflow includes `find_similar_assets_node`; graph chain is `START → ingest → context → similarity`. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0/0.5/1/2/3 unit tests green. |
| **Trace eval — single run** | `.venv/bin/python -m pytest tests/evals/test_step_3_trace.py -v` | The eval follows the Step 2 pattern (observes the coordinator + mock-MongoDB recordings; does **not** observe individual workflow nodes directly — node firing is verified indirectly via the recorded MongoDB calls). Given the Argentina-vs-France operator prompt (reused from Step 2 with N images) and a mock corpus of historical assets carrying embeddings + `product_route` + `scores`: (a) coordinator called `run_event_pipeline` exactly once; (b) `event_metadata.outcome_type == "upset_victory"` (preserved from Step 2 assertion); (c) `_compute_image_embedding` patch invoked once per asset (mocked, no live Gemini calls); (d) mock client recorded one `update-many` on `assets` per ingested asset setting `embedding` (length 3072); (e) mock client recorded one `aggregate` on `assets` per asset whose pipeline starts with `$vectorSearch` carrying `index="assets_embedding_index"`, `path="embedding"`, `numCandidates >= 10 × top_k`, `limit == top_k`, and a `$match` excluding the current `event_id`; (f) mock client recorded one `update-many` on `assets` per asset setting `similar_assets` (list of asset_ids from the mocked neighbor fixture); (g) the recorded order is `ingest writes (events + assets insert-many)` → `context reads/writes` → `similarity writes (embedding update-many → vectorSearch aggregate → similar_assets update-many)` — verified by mock_client.calls index order; (h) reasoning text from the coordinator appears before the dispatch tool call (CoT directive still firing); (i) on assertion failure, full trace dumped via `dump_trace()`. |
| **Trace eval — pass rate** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_3_trace.py -v` | ≥ 19/20 runs pass all nine assertions (95% threshold per D-020). |

Step 3's eval exercises **failure categories 1, 3, 5** per `evaluation-strategy.md`: tool selection (workflow advances through similarity node), tool arguments (correct vector-search pipeline shape — index name, path, top-K, exclude filter), end-state (embeddings + neighbor lists persisted; session state populated). Category 4 (tool-output handling) is downgraded relative to Step 2 — no LLM inside the capability means no hallucination surface. Category 6 (strategy coherence) does not apply until `propose_review_queue` ships.

---

## Output consumed by

- **`propose_review_queue` (capability 5)** — reads `similarity_results` from session state; refuses queue assembly if absent. Uses neighbor `scores` + `product_route` + similarity values as the exploitation-queue signal. Routes to the discovery queue when `neighbors` is empty or all similarity scores are below a threshold (the threshold is Step 5's choice, not Step 3's).
- **`draft_campaigns_for_queue` (capability 6)** — reads `Asset.similar_assets` from MongoDB; uses neighbor `product_route` as the dominant routing signal for campaign copy.
- **The trace** — judges watching the demo see the load-bearing MongoDB `$vectorSearch` aggregate call appear with explicit index name + dimensions + top-K. This is the partner-track integration moment. Per D-021 § "Explicit similarity", this must remain a discrete capability that surfaces in the trace, not bundled into a higher-level operation.

---

## What changed from prior planning docs

- **First purely-deterministic, non-MongoDB-external-dep capability.** Step 1 was deterministic with MongoDB-only. Step 2 added an internal LLM call. Step 3 adds Vertex AI as an external dependency (for embeddings) but no internal LLM call. The pattern that emerges: each step adds one new orthogonal dependency surface.
- **New `Asset.similar_assets` field on the Pydantic model.** The architecture spec implies it exists; this step makes it explicit and typed. Stored as `list[str]` (asset_ids only — full neighbor metadata stays in `similarity_results` session state and is not re-persisted on every read, to keep the asset document small).
- **New `prompts/v3/...` directory does not gain a Step 3 prompt.** No capability-internal LLM means no capability-internal prompt template. Coordinator prompt unchanged.
- **New provisioning artifact: `scripts/setup_vector_index.py`** — one-time idempotent Atlas vector-index create. Separate from the per-PR test path; lives outside `tests/` for clarity that it is operational, not test-shaped.
- **Seed pipeline extension is a Step 3 task, not a Step 0 backfill.** `scripts/seed_mongodb.py` gets an embedding pass added inline. The `--vector-only` re-embed flag exists for iteration during this step.

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

These are not optional follow-ups — implementation code in this branch must not contradict the spec it's written against.

1. **`docs/specs/02-architecture.md` § MongoDB schema + § MCP call list update.** Add `similar_assets: list[str] | null` to the `assets` collection JSON example. Add the explicit `$vectorSearch` pipeline shape under `find_similar_assets` in the MCP call list. Add the `assets_embedding_index` definition (name, dimensions, similarity) to a new "Atlas Vector Search indexes" subsection of the architecture spec.
2. **`docs/plans/db-wrapper-inventory.md` § `find_similar_assets` table — update signature.** Replace `vector_search_assets(embedding, top_k=20, channel=None)` with `vector_search_assets(embedding, top_k=5, exclude_event_id=None)`. The `channel` parameter is dropped (per-channel routing is Step 5's judgment surface, not a wrapper concern); `exclude_event_id` is added (prevents self-matching); `top_k` default lowered from 20 to 5 (see § Decisions taken). Note the rationale inline in the inventory table.
3. **`tracking.md` new D-entry — Step 3 architecture choices.** Capture (a) similarity metric = `cosine`; (b) default top_k = 5; (c) vector index provisioned via a one-time setup script (not at runtime); (d) `google.genai` SDK + `GOOGLE_API_KEY` is the embedding auth path (reconciles with D-006's "Vertex AI" framing — same model, different SDK surface; flip to Vertex auth later is a one-line client-construction change behind the helper); (e) current event's assets get embedded (not only historical) so today's batch becomes tomorrow's corpus — the feedback-loop seed. These are real architectural choices that should be searchable in `tracking.md`.

Sequence on this branch:
1. Branch housekeeping commit (items 1–3 above) — doc-only, no code.
2. Plan + tasks gates (this document + the task list).
3. Implementation commits per task ordering.
4. Trace eval and pass-rate gate.
5. Merge to `main` with the updated "Next action" line in `CLAUDE.md`.

---

## Decisions taken in this plan (confirm or override)

These are committed-to in the plan body. Listed here so a reviewer can scan them quickly and flag any to reverse before tasks are written.

- **Vector index provisioning is setup-time, not lazy.** A separate script (`scripts/setup_vector_index.py`) creates the Atlas vector-search index. Lazy creation rejected: couples runtime to Atlas Admin API and adds minutes of cold-start latency on first call.
- **Current event's assets get embedded** (not only historical). Today's assets become tomorrow's similarity corpus — the feedback-loop seed. Skipping this would scope Step 3 narrowly to "search against pre-existing corpus only" and defer corpus growth to Step 9 (record_outcomes); rejected because the embedding compute is already happening for search and the persisted column makes the corpus grow for free.
- **Seed pipeline embeds eagerly** (`scripts/seed_mongodb.py` writes embeddings inline with the historical asset inserts). Lazy seeding would couple the trace eval's mocked vector search to seed ordering.
- **SDK and auth path: `google.genai` with `GOOGLE_API_KEY`** matching Step 2's existing path (`src/capabilities/context.py:22`). D-006's "Vertex AI" framing is reconciled in the new D-entry — same model, different SDK surface; flippable later behind the `_compute_image_embedding` helper.
- **`vector_search_assets` signature deviates from `db-wrapper-inventory.md`:** drops `channel` (Step 5 concern), adds `exclude_event_id`, lowers `top_k` default from 20 → 5. Inventory updated in branch housekeeping item #2.
- **Top-K = 5 (confirmed at human gate).** Revisitable in Step 5 planning if the exploitation queue feels brittle, but lands here as the implementation default.
- **Similarity metric = `cosine` (confirmed at human gate).** Standard for Gemini image embeddings; cosine ≈ dotProduct on L2-normalized outputs.
- **Seed-time embedding pass: fail-fast (confirmed at human gate).** Unreachable image during `scripts/seed_mongodb.py` raises and aborts the seed. Surfaces provisioning problems immediately rather than at search time.
