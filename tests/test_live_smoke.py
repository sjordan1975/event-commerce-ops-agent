"""Live Atlas smoke tests — gated behind the `live` marker (deselected by default).

These hit the real MongoDB Atlas cluster to verify contracts the mocked unit suite
structurally cannot: that the vector index actually exists under the queried name with
the right shape (incl. the `event_id` filter field), that filtered `$vectorSearch`
returns cross-event neighbors instead of zero, and that real stored documents still
validate against the Pydantic models.

Run with:  pytest -m live      (needs MONGODB_URI; reads .env)

Transport note: production talks to Mongo through the MCP wrapper (`src/db`), but the
ADK/npx stdio client cold-starts per process and is too slow/flaky for a test. These
checks use pymongo directly — the regressions guarded here (index name/shape, the
exclusion pre-filter, model-vs-data drift) all live at the data layer, not the MCP
transport. The wrapper's pipeline *construction* is covered by tests/test_step_3.py;
this proves the query the wrapper builds actually works against the live index.
"""

import os

import pytest

pytest.importorskip("pymongo")
from pymongo import MongoClient

from src.db.assets import NUM_CANDIDATES_MULTIPLIER
from src.models import Asset, Event, Player, SimilarAsset

pytestmark = pytest.mark.live

DB_NAME = "event_commerce"
INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME", "assets_embedding_index")
TOP_K = 5


@pytest.fixture(scope="module")
def db():
    from dotenv import load_dotenv

    load_dotenv()
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        pytest.skip("MONGODB_URI not set — live Atlas tests skipped")
    client = MongoClient(uri)
    try:
        yield client[DB_NAME]
    finally:
        client.close()


@pytest.fixture(scope="module")
def query_event(db) -> str:
    """An event_id with an embedded asset, given ≥2 such events exist (so exclusion is meaningful)."""
    events = db.assets.distinct("event_id", {"embedding": {"$type": "array"}})
    if len(events) < 2:
        pytest.skip(f"need ≥2 events with embeddings for cross-event search; found {len(events)}")
    return events[0]


def test_vector_index_exists_with_event_id_filter(db):
    """The index the wrapper queries must exist, be queryable, and carry the event_id filter."""
    indexes = {i["name"]: i for i in db.assets.list_search_indexes()}
    assert INDEX_NAME in indexes, (
        f"vector index {INDEX_NAME!r} missing — find_similar_assets would return nothing"
    )
    idx = indexes[INDEX_NAME]
    assert idx.get("queryable") is True, f"index {INDEX_NAME!r} not queryable: {idx.get('status')}"

    fields = idx["latestDefinition"]["fields"]
    vectors = [f for f in fields if f["type"] == "vector"]
    filters = [f["path"] for f in fields if f["type"] == "filter"]
    assert len(vectors) == 1 and vectors[0]["path"] == "embedding"
    assert vectors[0]["numDimensions"] == 3072  # gemini-embedding-2 output (D-006)
    assert vectors[0]["similarity"] == "cosine"
    # event_id filter field is load-bearing for the exclusion pre-filter (D-034).
    assert "event_id" in filters, (
        "event_id filter field missing — the find_similar_assets exclusion would empty results"
    )


def test_filtered_vector_search_returns_cross_event_neighbors(db, query_event):
    """The exact pipeline vector_search_assets builds must return cross-event neighbors, not zero.

    Guards the regression where a post-$match exclusion ran after `limit`, so same-event
    neighbors filled all top_k slots and were discarded → 0 results (D-034).
    """
    doc = db.assets.find_one(
        {"event_id": query_event, "embedding": {"$type": "array"}}, {"embedding": 1}
    )
    qvec = doc["embedding"]

    pipeline = [
        {
            "$vectorSearch": {
                "index": INDEX_NAME,
                "path": "embedding",
                "queryVector": qvec,
                "numCandidates": NUM_CANDIDATES_MULTIPLIER * TOP_K,
                "limit": TOP_K,
                "filter": {"event_id": {"$ne": query_event}},
            }
        },
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
    rows = list(db.assets.aggregate(pipeline))

    assert rows, "filtered vector search returned 0 neighbors — index/exclusion regression"
    assert len(rows) <= TOP_K
    assert all(r["event_id"] != query_event for r in rows), (
        "same-event leakage despite the exclusion pre-filter"
    )
    # Results must parse as the real return model (catches projection/score drift).
    neighbors = [SimilarAsset.model_validate(r) for r in rows]
    assert all(0.0 <= n.similarity <= 1.0 for n in neighbors)


@pytest.mark.parametrize(
    "collection, model",
    [("assets", Asset), ("events", Event), ("player_context", Player)],
)
def test_real_documents_validate_against_models(db, collection, model):
    """Real stored docs must validate against the Pydantic models after the wrappers' _id strip.

    Guards seed/schema drift (e.g. extra fields under extra='forbid' models, like the
    removed assets.scored_at/published_at, D-034) that the mocked suite cannot see.
    """
    doc = db[collection].find_one()
    if doc is None:
        pytest.skip(f"{collection} is empty")
    model.model_validate({k: v for k, v in doc.items() if k != "_id"})


@pytest.mark.anyio
async def test_mcp_wrapper_parses_real_find_envelope():
    """A real MCP `find` through the wrapper must parse — guards the envelope-parse bug.

    The server wraps results in <untrusted-user-data-UUID> tags, but its security preamble
    references those tags inline, so a non-greedy parser captured "and" and threw. This is
    the only test that exercises _parse_docs_response against the REAL server (the pymongo
    tests above bypass it). Boots the vendored MCP binary (no npx) for a reliable cold start.
    """
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("MONGODB_URI"):
        pytest.skip("MONGODB_URI not set")
    bin_path = Path(__file__).resolve().parents[1] / "src/api/node_modules/.bin/mongodb-mcp-server"
    if not bin_path.exists():
        pytest.skip("vendored mongodb-mcp-server not installed (npm install in src/api)")
    os.environ["MONGODB_MCP_COMMAND"] = str(bin_path)

    import src.db as dbmod

    dbmod._client = None  # fresh singleton so it picks up MONGODB_MCP_COMMAND
    from src.db.assets import get_assets_for_event

    client = dbmod.get_client()
    await client.warm(timeout=45)
    try:
        # 10 full asset docs incl. 3072-dim embeddings — the call that originally threw.
        assets = await get_assets_for_event("wc2022-final-arg-fra")
        assert len(assets) == 10, f"expected 10 parsed assets, got {len(assets)}"
        assert all(a.event_id == "wc2022-final-arg-fra" for a in assets)
    finally:
        await client.close()
        dbmod._client = None
