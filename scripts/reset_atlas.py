"""
Reset event_commerce to seeded-but-pre-run state.

Deletes all pipeline-created documents (campaigns, approvals, and any events /
assets / performance rows created by a pipeline run) while leaving the seed
corpus intact: 4 historical events, 64 seed assets, 64 baseline performance
records, and 16 player_context bios.

Safe to run between demo runs. Idempotent — running it on an already-clean
database is a no-op (deletes 0 rows, reports correct counts).

Seed corpus baseline: 4 events, 64 assets, 64 performance records, 25 player_context bios.

Usage:
    python scripts/reset_atlas.py

Requires:
    MONGODB_URI — Atlas connection string (read from .env)
"""

import os
import sys

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGODB_URI = os.environ.get("MONGODB_URI")
DB_NAME = "event_commerce"

# The 4 seed events are the permanent historical corpus. Every document
# whose event_id is NOT in this set was created by a pipeline run.
SEED_EVENT_IDS = [
    "wc2022-final-arg-fra",
    "wc2018-grp-kor-ger",
    "wc2014-final-ger-arg",
    "wc2018-grp-esp-por",
]

NON_SEED_FILTER = {"event_id": {"$nin": SEED_EVENT_IDS}}


def reset(db) -> None:
    print("Resetting event_commerce to seeded-but-pre-run state...\n")

    # campaigns — always empty at seed; delete all pipeline-created rows
    r = db.campaigns.delete_many({})
    print(f"  campaigns:     deleted {r.deleted_count:>4}  →  {db.campaigns.count_documents({})} remaining")

    # approvals — always empty at seed; delete all pipeline-created rows
    r = db.approvals.delete_many({})
    print(f"  approvals:     deleted {r.deleted_count:>4}  →  {db.approvals.count_documents({})} remaining")

    # events — keep the 4 seed events; remove any event the pipeline created
    r = db.events.delete_many(NON_SEED_FILTER)
    print(f"  events:        deleted {r.deleted_count:>4}  →  {db.events.count_documents({})} remaining (expected 4)")

    # assets — keep the 40 seed images; remove any asset the pipeline created
    r = db.assets.delete_many(NON_SEED_FILTER)
    print(f"  assets:        deleted {r.deleted_count:>4}  →  {db.assets.count_documents({})} remaining (expected 64)")

    # performance — keep the 64 baseline metrics; remove any run-created rows
    r = db.performance.delete_many(NON_SEED_FILTER)
    print(f"  performance:   deleted {r.deleted_count:>4}  →  {db.performance.count_documents({})} remaining (expected 64)")

    # player_context — never touched by the pipeline; report count only
    n = db.player_context.count_documents({})
    print(f"  player_context: untouched              →  {n} remaining (expected 25)")

    print("\nDone.")


def main() -> None:
    if not MONGODB_URI:
        print("ERROR: MONGODB_URI not set", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(MONGODB_URI)
    try:
        reset(client[DB_NAME])
    finally:
        client.close()


if __name__ == "__main__":
    main()
