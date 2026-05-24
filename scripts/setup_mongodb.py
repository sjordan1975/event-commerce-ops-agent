"""
Provision the event_commerce database: create collections and indexes.

Run once against a fresh Atlas cluster. Safe to re-run — existing
collections and indexes are left untouched.

Usage:
    python scripts/setup_mongodb.py
"""

import os
import sys
from pymongo import MongoClient
from pymongo.errors import CollectionInvalid
from pymongo.operations import SearchIndexModel


MONGODB_URI = os.environ.get("MONGODB_URI")
DB_NAME = "event_commerce"

COLLECTIONS = ["events", "assets", "campaigns", "approvals", "performance"]

CLASSIC_INDEXES = {
    "events": [
        ({"event_id": 1}, "event_id_unique"),
        ({"outcome_type": 1}, "outcome_type"),
    ],
    "assets": [
        ({"asset_id": 1}, "asset_id_unique"),
        ({"event_id": 1, "status": 1}, "event_id_status"),
        ({"campaign_id": 1}, "campaign_id"),
    ],
    "campaigns": [
        ({"campaign_id": 1}, "campaign_id_unique"),
        ({"asset_id": 1, "status": 1}, "asset_id_status"),
    ],
    "approvals": [
        ({"approval_id": 1}, "approval_id_unique"),
        ({"campaign_id": 1, "status": 1}, "campaign_id_status"),
    ],
    "performance": [
        ({"asset_id": 1, "campaign_id": 1, "event_id": 1}, "asset_campaign_event"),
    ],
}

# Vector search index on assets.embedding
# 3072 dimensions: gemini-embedding-2 output size
# cosine similarity: standard for normalized Gemini embeddings
# pre-filters on event_id and status allow scoped search without a collection scan
VECTOR_SEARCH_INDEX = SearchIndexModel(
    definition={
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 3072,
                "similarity": "cosine",
                "quantization": "none",
            },
            {"type": "filter", "path": "event_id"},
            {"type": "filter", "path": "status"},
        ]
    },
    name="embedding_vector_search",
    type="vectorSearch",
)


def main() -> None:
    if not MONGODB_URI:
        print("Error: MONGODB_URI environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]

    # Collections
    existing = set(db.list_collection_names())
    for name in COLLECTIONS:
        if name in existing:
            print(f"  collection exists, skipping: {name}")
        else:
            db.create_collection(name)
            print(f"  created collection: {name}")

    # Classic indexes
    for collection_name, indexes in CLASSIC_INDEXES.items():
        col = db[collection_name]
        existing_indexes = {idx["name"] for idx in col.list_indexes()}
        for keys, index_name in indexes:
            if index_name in existing_indexes:
                print(f"  index exists, skipping: {collection_name}.{index_name}")
            else:
                col.create_index(list(keys.items()), name=index_name)
                print(f"  created index: {collection_name}.{index_name}")

    # Vector search index (Atlas only — will fail against local mongod)
    assets = db["assets"]
    existing_search = {idx["name"] for idx in assets.list_search_indexes()}
    if "embedding_vector_search" in existing_search:
        print("  vector search index exists, skipping: assets.embedding_vector_search")
    else:
        assets.create_search_index(VECTOR_SEARCH_INDEX)
        print("  created vector search index: assets.embedding_vector_search")

    print("\nDone.")
    client.close()


if __name__ == "__main__":
    main()
