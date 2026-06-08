# Event Commerce Ops Agent

> *Sports moments decay commercially, fast. The bottleneck isn't the photography — it's everything after the shutter closes.*

An AI agent that triages live event media and orchestrates the full monetization pipeline — from a batch of post-match photos to published Shopify listings and a queued social post — with a human operator in the loop.

Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) (MongoDB partner track).

---

## What it does

An operator drops a batch of event photos and a natural-language description into the console. The agent runs nine capabilities in sequence:

1. **Ingest** — record the event, bulk-insert all images into Atlas
2. **Build context** — synthesize an event narrative grounded in historical performance data and player biographies
3. **Find similar assets** — embed each image via `gemini-embedding-2` and vector-search against a corpus of past high-performing assets
4. **Score assets** — Gemini Vision scores each frame across five commercial dimensions: quality, emotional intensity, social scroll-stop probability, merch suitability, and fan identity signal
5. **Propose the review queue** — the one strategic decision: which assets get surfaced, in what order, with what rationale
6. **Draft campaigns** — generate copy for each queued asset, grounded in the event narrative
7. **Request human approval** — nothing executes until the operator signs off
8. **Execute** — Gemini-generated mockup image uploaded to Shopify, product listing created, social post queued in Atlas
9. **Record outcomes** — write provenance records to feed the next run's similarity search

MongoDB is load-bearing at every step. Removing the MCP would not degrade the system — it would break it.

### The queue assembly decision

Step 5 is where the agent earns its keep. It operates on two tracks:

**Exploitation:** assets that resemble past high-performers are identified by vector search. Routing is determined by a similarity-weighted plurality vote over historical `product_route` assignments. The LLM cannot override this; historical signal governs.

**Exploration:** assets with no strong precedent are evaluated on their own merits — raw vision scores, event narrative, image content — with a one-sentence rationale on every pick. *"This didn't match past winners, but captures the goalkeeper's disbelief in a way the celebration photos don't — worth your time."*

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent orchestration | Google ADK v2.1 — coordinator chat loop + graph-wired `FunctionNode` pipeline |
| LLM | Gemini 2.5 Flash (coordinator, vision scoring); Flash Lite (workflow nodes, narrative) |
| Embeddings | `gemini-embedding-2` — 3072-dim multimodal, Vertex AI |
| Database / state | MongoDB Atlas — runtime state, vector search corpus, approval queue, commercial memory |
| MCP | MongoDB MCP Server — transport layer between agent capabilities and Atlas |
| Commerce | Shopify GraphQL Admin API; Gemini image gen → `stagedUploadsCreate` → `productCreateMedia` |
| Social | Simulated (Atlas queue written; no live platform API) |
| Backend | FastAPI + SSE streaming |
| Frontend | Next.js operator console |

---

## Prerequisites

- Python 3.13+
- Node.js 18+ (operator console)
- MongoDB Atlas cluster with vector search enabled
- Google AI API key (`GOOGLE_API_KEY`)
- Shopify Partners dev store (optional — runs in preview mode without it)

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.template .env
# Fill in GOOGLE_API_KEY, MONGODB_URI, MDB_MCP_API_CLIENT_ID, MDB_MCP_API_CLIENT_SECRET
```

See `.env.template` for the full variable reference. Required (no defaults):

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key (LLM + embeddings) |
| `MONGODB_URI` | Atlas connection string |
| `MDB_MCP_API_CLIENT_ID` | MongoDB Atlas MCP auth |
| `MDB_MCP_API_CLIENT_SECRET` | MongoDB Atlas MCP auth |

Shopify credentials (`SHOPIFY_STORE_URL`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`) are optional. Without them the agent runs in preview mode — mockups are stored locally and served at `/api/mockup/{asset_id}`.

### 3. Seed MongoDB

```bash
# Create collections and indexes
python scripts/setup_mongodb.py

# Provision the Atlas Vector Search index (3072-dim cosine on assets.embedding)
python scripts/setup_vector_index.py

# Seed the historical performance corpus (64 assets with real embeddings)
python scripts/seed_mongodb.py
```

All three scripts are idempotent — safe to re-run against an existing cluster.

| Collection | Purpose |
|---|---|
| `events` | One doc per live event |
| `assets` | One doc per image; updated at every step; vector search on `embedding` |
| `campaigns` | Campaign drafts |
| `approvals` | Human review queue |
| `performance` | Post-execution metrics — the commercial memory that compounds across events |

---

## Run

**Backend** (FastAPI + SSE, port 8000):

```bash
.venv/bin/python -m uvicorn src.api.server:app --port 8000 --reload
```

**Operator console** (Next.js, port 3000):

```bash
cd ui
npm install
# Point the UI at the backend:
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open `http://localhost:3000`. The MCP health badge in the sidebar shows the MongoDB connection lifecycle. Send a message to start a pipeline run.

> **Deployed:** set `NEXT_PUBLIC_API_URL` to the backend's public URL (e.g. your DigitalOcean Droplet address). Without it the UI falls back to built-in mock data.

**Demo reset** between runs:

```bash
python scripts/reset_atlas.py
```

---

## Test

```bash
.venv/bin/python -m pytest tests/ --ignore=tests/evals -q
```

211 unit tests + scaffolding tests. Live evals (against real Atlas and Gemini) live under `tests/evals/` and are excluded by default.

---

## Architecture

See [`docs/specs/02-architecture.md`](docs/specs/02-architecture.md) for the full system design, 9-capability pipeline, MongoDB schemas, MCP call list, and ADK agent architecture.
