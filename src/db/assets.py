"""Internal MongoDB wrapper for the assets collection."""

import os

from src.db import _parse_docs_response, get_client
from src.models import Asset, AssetScores, SimilarAsset



NUM_CANDIDATES_MULTIPLIER = 10  # numCandidates = NUM_CANDIDATES_MULTIPLIER * top_k (Atlas guidance for high-recall vector search)


async def record_assets(event_id: str, assets: list[Asset]) -> list[str]:
    """Internal: bulk-records image assets for an event. Called by the
    `ingest_event_batch` capability; not agent-facing. Returns asset_ids in input order."""
    for asset in assets:
        asset.status = "ingested"
    await get_client().call("insert-many", {
        "database": "event_commerce",
        "collection": "assets",
        "documents": [a.model_dump(mode="json") for a in assets],
    })
    return [a.asset_id for a in assets]


async def get_assets_for_event(event_id: str, status: str | None = None) -> list[Asset]:
    """Return all assets for an event, optionally filtered by status."""
    filter_dict: dict = {"event_id": event_id}
    if status is not None:
        filter_dict["status"] = status
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": filter_dict,
        "limit": 500,  # MCP default is 10; override to return full event batch
    })
    docs = _parse_docs_response(envelope)
    return [Asset.model_validate({k: v for k, v in doc.items() if k != "_id"}) for doc in docs]


async def vector_search_assets(
    embedding: list[float],
    top_k: int = 5,
    exclude_event_id: str | None = None,
) -> list[SimilarAsset]:
    """Run Atlas $vectorSearch against historical assets, returning top-K neighbors.

    Uses the assets_embedding_index (cosine, 3072-dim). The load-bearing MongoDB
    partner-track integration (D-001, D-006, D-021)."""
    index_name = os.environ.get("VECTOR_INDEX_NAME", "assets_embedding_index")
    vector_search: dict = {
        "index": index_name,
        "path": "embedding",
        "queryVector": embedding,
        "numCandidates": NUM_CANDIDATES_MULTIPLIER * top_k,
        "limit": top_k,
    }
    # Exclude the query's own event *inside* $vectorSearch (pre-filter), not as a
    # post-$match: a post-stage runs after limit, so same-event neighbors fill all
    # top_k slots and get discarded, yielding zero. Requires event_id as an index
    # filter field (see scripts/setup_vector_index.py).
    if exclude_event_id is not None:
        vector_search["filter"] = {"event_id": {"$ne": exclude_event_id}}
    pipeline = [
        {"$vectorSearch": vector_search},
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
    envelope = await get_client().call("aggregate", {
        "database": "event_commerce",
        "collection": "assets",
        "pipeline": pipeline,
    })
    docs = _parse_docs_response(envelope)
    return [SimilarAsset.model_validate(doc) for doc in docs]


async def mark_asset_executing(asset_id: str) -> None:
    """Pre-execution state transition — visible in trace for debugging."""
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {"status": "executing"}},
    })


async def get_assets_by_ids(asset_ids: list[str]) -> list[Asset]:
    """Fetch assets by a list of asset_ids (display-batch join helper)."""
    if not asset_ids:
        return []
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": {"$in": asset_ids}},
        "limit": 500,
    })
    docs = _parse_docs_response(envelope)
    return [Asset.model_validate({k: v for k, v in doc.items() if k != "_id"}) for doc in docs]


async def save_asset_embedding(asset_id: str, embedding: list[float]) -> None:
    """Persist a computed embedding to the asset document (permanent — idempotent skip is caller's responsibility)."""
    if len(embedding) != 3072:
        raise ValueError(f"embedding dimension mismatch: expected 3072, got {len(embedding)}")
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {"embedding": embedding}},
    })


async def save_similar_assets(asset_id: str, similar_asset_ids: list[str]) -> None:
    """Persist the neighbor asset_id list (analytical — recomputable if corpus grows)."""
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {"similar_assets": similar_asset_ids}},
    })


async def save_asset_scores(
    asset_id: str,
    scores: AssetScores,
    detected_subjects: list[str],
) -> None:
    """Persist scores + detected_subjects + status transition in one update."""
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {
            "scores": scores.model_dump(mode="json"),
            "detected_subjects": detected_subjects,
            "status": "scored",
        }},
    })


async def save_queue_assignment(
    asset_id: str,
    queue_type: str,
    product_route: str | None,
    rank: int,
    rationale: str,
) -> None:
    """Persist queue assignment fields onto the asset document.

    Does NOT change status — assets stay 'scored' until Step 6 sets
    'campaign_draft_created' (D-029). Writes queue_type, product_route,
    queue_rank, queue_rationale only.
    """
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {
            "queue_type": queue_type,
            "product_route": product_route,
            "queue_rank": rank,
            "queue_rationale": rationale,
        }},
    })
