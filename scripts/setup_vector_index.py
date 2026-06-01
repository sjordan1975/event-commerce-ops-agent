"""Provision the Atlas Vector Search index for the assets embedding column.

One-time idempotent script — safe to re-run. Polls until the index is READY
(timeout 10 minutes) so the operator gets a clear "done" signal.

Usage:
    python scripts/setup_vector_index.py

Reads MONGODB_URI from env. Atlas API credentials (MDB_MCP_API_CLIENT_ID /
MDB_MCP_API_CLIENT_SECRET) are not required — uses the PyMongo driver's
search-index API which goes through the connection string.
"""

import os
import sys
import time

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME", "assets_embedding_index")
DB_NAME = "event_commerce"
COLLECTION_NAME = "assets"
POLL_INTERVAL_S = 10
TIMEOUT_S = 600  # 10 minutes


def _get_client() -> MongoClient:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("ERROR: MONGODB_URI environment variable not set.", file=sys.stderr)
        sys.exit(1)
    return MongoClient(uri)


def _index_exists(collection) -> bool:
    for idx in collection.list_search_indexes():
        if idx.get("name") == INDEX_NAME:
            return True
    return False


def _index_status(collection) -> str | None:
    for idx in collection.list_search_indexes():
        if idx.get("name") == INDEX_NAME:
            return idx.get("status")
    return None


def main() -> None:
    client = _get_client()
    collection = client[DB_NAME][COLLECTION_NAME]

    if _index_exists(collection):
        print(f"index '{INDEX_NAME}' already exists — no-op.")
        return

    print(f"Creating vector search index '{INDEX_NAME}' ...")
    model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 3072,
                    "similarity": "cosine",
                },
                # event_id is a filter field so find_similar_assets can exclude the
                # query's own event *inside* $vectorSearch (pre-filter). Without it the
                # top_k slots get consumed by same-event neighbors that a post-stage
                # would then discard, returning zero. See vector_search_assets.
                {"type": "filter", "path": "event_id"},
            ]
        },
        name=INDEX_NAME,
        type="vectorSearch",
    )
    collection.create_search_index(model)
    print("Index creation submitted. Waiting for READY status ...")

    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        status = _index_status(collection)
        if status == "READY":
            print(f"index '{INDEX_NAME}' created and READY.")
            return
        print(f"  status: {status} — waiting {POLL_INTERVAL_S}s ...")
        time.sleep(POLL_INTERVAL_S)

    print(
        f"ERROR: index '{INDEX_NAME}' did not reach READY within {TIMEOUT_S}s. "
        "Check Atlas console for details.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
