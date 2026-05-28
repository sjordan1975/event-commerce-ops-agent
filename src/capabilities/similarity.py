"""find_similar_assets — Step 3 capability: embed + Atlas Vector Search."""

import asyncio
import os
import urllib.request

from google import genai
from google.genai import types as genai_types

from src.db.assets import (
    get_assets_for_event,
    save_asset_embedding,
    save_similar_assets,
    vector_search_assets,
)
from src.errors import PreconditionError
from src.models import SimilarAsset

DEFAULT_TOP_K = 5


def _compute_image_embedding(image_url: str) -> list[float]:
    """Fetch image bytes from a local path or HTTP URL, then embed via gemini-embedding-2.

    Uses Part.from_bytes(data=..., mime_type="image/jpeg") — the only supported
    image input form for gemini-embedding-2 (task_type not supported by this model).
    """
    api_key = os.environ["GOOGLE_API_KEY"]
    model = os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")

    if image_url.startswith("http://") or image_url.startswith("https://"):
        with urllib.request.urlopen(image_url) as resp:
            image_bytes = resp.read()
    else:
        with open(image_url, "rb") as f:
            image_bytes = f.read()

    client = genai.Client(api_key=api_key)
    # Part.from_bytes is the supported image input form for gemini-embedding-2
    part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    response = client.models.embed_content(
        model=model,
        contents=[part],
        config=genai_types.EmbedContentConfig(output_dimensionality=3072),
    )
    result = response.embeddings[0].values
    if len(result) != 3072:
        raise ValueError(f"embedding dimension mismatch: expected 3072, got {len(result)}")
    return list(result)


def _infer_route_from_neighbors(neighbors: list[SimilarAsset]) -> str | None:
    """Mechanical routing inference: plurality vote over neighbors' product_route,
    similarity-weighted tie-break. Returns None when neighbors is empty (the
    asset is a discovery-queue candidate, route assignment deferred to Step 5).
    Not judgment — see D-025."""
    if not neighbors:
        return None
    weights: dict[str, float] = {}
    for n in neighbors:
        if n.product_route is None:
            continue
        weights[n.product_route] = weights.get(n.product_route, 0.0) + n.similarity
    if not weights:
        return None
    # max by (weight, route) — deterministic on weight tie via lexicographic route order
    return max(weights.items(), key=lambda kv: (kv[1], kv[0]))[0]


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

    # Search + infer-route + persist loop (runs for every asset regardless of embedding source)
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
            "inferred_route": _infer_route_from_neighbors(neighbors),
        })
        await save_similar_assets(asset.asset_id, [n.asset_id for n in neighbors])

    return {"event_id": event_id, "similar": similarity_results}
