"""Capture real MongoDB MCP envelopes as test fixtures.

Manual — needs a live server + Atlas. Boots the vendored MCP binary, runs a few
representative calls, and writes the raw envelopes to tests/fixtures/mcp/ so the
hermetic contract tests (tests/test_mcp_contract.py) can replay *real* server
responses without a server. Re-run when MONGODB_MCP_VERSION changes.

Usage:
    MONGODB_URI=... python scripts/capture_mcp_fixtures.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))  # allow `python scripts/...` to import src.db
_VENDORED_BIN = _ROOT / "src" / "api" / "node_modules" / ".bin" / "mongodb-mcp-server"
# Default to the vendored binary (direct exec, no npx/registry) unless overridden.
os.environ.setdefault("MONGODB_MCP_COMMAND", str(_VENDORED_BIN))

FIXTURE_DIR = _ROOT / "tests" / "fixtures" / "mcp"
DB = "event_commerce"
EVENT = "wc2022-final-arg-fra"


async def main() -> None:
    from src.db import _parse_docs_response, get_client

    if not os.environ.get("MONGODB_URI"):
        raise SystemExit("MONGODB_URI not set")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    client = get_client()
    await client.warm(timeout=45)

    fixtures: dict[str, dict] = {}

    # find, non-empty — projected small (no 3072-dim embeddings); reproduces the
    # preamble-parse shape without a 400KB payload.
    fixtures["find_nonempty"] = await client.call("find", {
        "database": DB, "collection": "assets", "filter": {"event_id": EVENT},
        "projection": {"asset_id": 1, "event_id": 1, "product_route": 1, "_id": 0},
    })
    # find, empty — server returns the summary part only, no wrapper.
    fixtures["find_empty"] = await client.call("find", {
        "database": DB, "collection": "assets", "filter": {"event_id": "__no_such_event__"},
    })
    # aggregate $vectorSearch — the other parse path (and a different tool).
    one = await client.call("find", {
        "database": DB, "collection": "assets", "filter": {"event_id": EVENT},
        "projection": {"embedding": 1, "_id": 0}, "limit": 1,
    })
    qvec = _parse_docs_response(one)[0]["embedding"]
    fixtures["aggregate_vectorsearch"] = await client.call("aggregate", {
        "database": DB, "collection": "assets",
        "pipeline": [
            {"$vectorSearch": {
                "index": os.environ.get("VECTOR_INDEX_NAME", "assets_embedding_index"),
                "path": "embedding", "queryVector": qvec, "numCandidates": 50, "limit": 5,
                "filter": {"event_id": {"$ne": EVENT}},
            }},
            {"$project": {"_id": 0, "asset_id": 1, "event_id": 1, "product_route": 1,
                          "scores": 1, "similarity": {"$meta": "vectorSearchScore"}}},
        ],
    })

    await client.close()

    for name, env in fixtures.items():
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(json.dumps(env, indent=2, ensure_ascii=False))
        print(f"  wrote {path.relative_to(_ROOT)}  ({len(_parse_docs_response(env))} docs)")


if __name__ == "__main__":
    asyncio.run(main())
