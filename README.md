# Event Commerce Ops Agent

![Tests](https://github.com/sjordan1975/event-commerce-ops-agent/actions/workflows/test.yml/badge.svg)
![Version](https://img.shields.io/github/v/tag/sjordan1975/event-commerce-ops-agent?label=version)
![Python](https://img.shields.io/badge/python-3.13-blue)
![TypeScript](https://img.shields.io/badge/typescript-5-blue)
![Next.js](https://img.shields.io/badge/Next.js-15-black)

> *Sports moments decay commercially, fast. The bottleneck isn't the photography — it's everything after the shutter closes.*

An AI agent that triages live event media and orchestrates the full monetization pipeline — from a batch of post-match photos to published Shopify listings and a queued social post — with a human operator in the loop.

Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) (MongoDB partner track).

---

## What it does

An operator drops a batch of event photos (via uload in UI or referenced as URLs) and a natural-language description into the console. The agent runs nine capabilities in sequence:

1. **Ingest** — record the event, create an asset document in Atlas for each image (images are referenced by URL or local path — not stored in Atlas)
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

## Try it

The live demo is running at **[https://event-commerce-ops-agent.vercel.app/](https://event-commerce-ops-agent.vercel.app/)** — no installation required.

Paste the following into the chat to run the full pipeline:

```text
France vs Croatia, 2018 FIFA World Cup Final.
France won 4–2 — a dominant victory. 
Match started 2018-07-15T15:00:00Z. 
Outcome: expected win.

https://upload.wikimedia.org/wikipedia/commons/2/29/Antoine_Griezmann_World_Cup_Trophy.jpg
https://upload.wikimedia.org/wikipedia/commons/6/61/Kylian_Mbapp%C3%A9_World_Cup_Trophy.jpg
https://upload.wikimedia.org/wikipedia/commons/1/14/France_celebrate_on_the_field_of_Luzhniki_after_the_2018_FIFA_World_Cup_Final.jpg
https://upload.wikimedia.org/wikipedia/commons/3/37/Djibril_Sidib%C3%A9_World_Cup_Trophy.jpg
```

The agent will ingest the images, build event context, score each asset, propose a review queue, and draft campaigns — then pause for your approval before publishing mocks.

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
- Node.js 18+ (operator console + vendored MongoDB MCP server binary)
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

Install the vendored MongoDB MCP server binary (required by the backend — spawned as a subprocess at runtime):

```bash
cd src/api && npm install && cd ../..
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

### Local development

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

### Deployed

You need two hosted services:

- **Backend** — deploy `src/api/server.py` (FastAPI/uvicorn) to any environment that can serve HTTP (e.g. DigitalOcean, Cloud Run, Railway)
- **Frontend** — deploy the `ui/` directory to a static hosting provider (e.g. Vercel)

Point the frontend at the backend by setting the following environment variable on your frontend host:

```sh
NEXT_PUBLIC_API_URL=https://your-backend-url
```

Without this variable the UI falls back to built-in mock data.

Once both are running, open your frontend URL. The MCP health badge in the sidebar confirms the MongoDB connection. Send a message to start a pipeline run.

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

---

## Notices

**Image credits:** Demo corpus images sourced from [Wikimedia Commons](https://commons.wikimedia.org/) under Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0). Product mockup images are AI-generated by Gemini and used for demonstration purposes only.

**Trademarks:** Shopify is a registered trademark of Shopify Inc. This project is not affiliated with or endorsed by Shopify Inc. Google, Gemini, and Vertex AI are trademarks of Google LLC. MongoDB and Atlas are trademarks of MongoDB, Inc.
