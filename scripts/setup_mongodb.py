"""
Provision the event_commerce database: create collections and classic indexes.

Run once against a fresh Atlas cluster. Safe to re-run — existing
collections and indexes are left untouched. The Atlas Vector Search index on
assets.embedding is provisioned separately by scripts/setup_vector_index.py
(single source of truth for the vector index — name + definition).

Usage:
    python scripts/setup_mongodb.py
"""

import os
import sys
from pymongo import MongoClient


MONGODB_URI = os.environ.get("MONGODB_URI")
DB_NAME = "event_commerce"

COLLECTIONS = ["events", "assets", "campaigns", "approvals", "performance", "player_context"]

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
    "player_context": [
        ({"team": 1}, "team"),
    ],
}


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

    print("\nDone. Run scripts/setup_vector_index.py to provision the vector search index.")
    client.close()


if __name__ == "__main__":
    main()
