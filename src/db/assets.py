"""Internal MongoDB wrapper for the assets collection."""

from src.db import get_client
from src.models import Asset


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
