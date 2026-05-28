# Real-Time Event Commerce Operations Agent

An AI agent that triages live event media and orchestrates monetization workflows across Shopify, Printful, and social — built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) (MongoDB partner track).

See `docs/specs/00-overview.md` for full project context and `tracking.md` for architectural decisions.

---

## Prerequisites

- Python 3.11+
- GCP project with Vertex AI enabled (ADC configured via `gcloud auth application-default login`)
- MongoDB Atlas cluster (connection string in `.env`)
- Shopify Partners dev store with Admin API token
- Printful account with private token

---

## Environment Variables

Copy `.env.template` to `.env` and fill in values:

```
# MongoDB MCP server
MONGODB_URI=mongodb+srv://...
MDB_MCP_API_CLIENT_ID=
MDB_MCP_API_CLIENT_SECRET=

# Google AI (google.genai SDK — used for coordinator, narrative LLM, and embeddings)
GOOGLE_API_KEY=

# Model selection
GEMINI_MODEL=gemini-2.5-flash-lite          # workflow nodes and internal helpers
GEMINI_COORDINATOR_MODEL=gemini-2.5-flash   # coordinator chat LlmAgent
GEMINI_NARRATIVE_MODEL=gemini-2.5-flash-lite  # build_event_context narrative LLM
GEMINI_EMBEDDING_MODEL=gemini-embedding-2   # image embeddings in find_similar_assets
GEMINI_VISION_MODEL=gemini-2.5-flash        # score_assets_with_vision (judgment-laden — not flash-lite)

# Atlas Vector Search (Step 3)
VECTOR_INDEX_NAME=assets_embedding_index    # Atlas vector search index name on assets.embedding

# Prompt version
PROMPT_VERSION=v3

# Shopify
SHOPIFY_STORE_URL=
SHOPIFY_ADMIN_TOKEN=

# Printful
PRINTFUL_TOKEN=
```

---

## MongoDB Setup

Database: **`event_commerce`**

Run the setup script once against a fresh cluster to create all collections and indexes:

```bash
MONGODB_URI=<your-uri> python scripts/setup_mongodb.py
```

The script is idempotent — safe to re-run; existing collections and indexes are left untouched.

| Collection | Purpose | Key indexes |
|---|---|---|
| `events` | One doc per live event; written at Step 1 | `event_id`, `outcome_type` |
| `assets` | One doc per image; updated at every step | `asset_id`, `event_id+status`, `campaign_id`, vector search on `embedding` |
| `campaigns` | Campaign drafts; written at Step 5 | `campaign_id`, `asset_id+status` |
| `approvals` | Human review queue; written at Step 5, resolved at Step 6 | `approval_id`, `campaign_id+status` |
| `performance` | Post-execution metrics; written at Step 8 | `asset_id+campaign_id+event_id` |

Vector search index on `assets.embedding`: 3072 dimensions (gemini-embedding-2), cosine similarity, pre-filters on `event_id` and `status`.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Run

_Not yet implemented — placeholder._

```bash
# TODO: entry point TBD
```

---

## Test

```bash
.venv/bin/python -m pytest
```

---

## Architecture

See `docs/specs/02-architecture.md` for the full system design, 9-capability pipeline, MCP call list, and ADK agent architecture.
