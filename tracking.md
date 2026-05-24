# Decision & Progress Tracking

## Current Status

**Phase:** Pre-code — concept locked, architecture decided, implementation not started  
**Deadline:** June 11, 2026 @ 2:00 PM PDT  
**Partner track:** MongoDB

---

## Decision Log

### D-001 — Partner Track: MongoDB (overrides D-000)
**Date:** 2026-05-23  
**Decision:** MongoDB, not Elastic  
**Supersedes:** D-000 (Elastic)

**Reasoning:**
- Applied the load-bearing test: *would removing this MCP cripple the agent?*
- MongoDB MCP is called in every one of the 8 workflow steps: ingestion, event context, vector search scoring, state updates, campaign queue, approval queue, execution logging, feedback loop
- Elastic's role reduced to ~1 retrieval query that Gemini could handle in-context. Not load-bearing.
- Elastic's partner page listed technical resources as "Coming soon" — real execution risk against a 19-day runway
- MongoDB has well-documented MCP server, sample datasets with pre-built vector embeddings (Mflix), no access friction

**Fivetran ruled out simultaneously:**
- Fivetran is a data warehouse ingestion tool (source → BigQuery/Snowflake), not a vendor pipeline
- Printers/manufacturers (Printful, Printify) expose REST APIs, not Fivetran connectors
- Fivetran's batch/scheduled architecture directly contradicts the "attention half-life" latency narrative

---

### D-000 — Partner Track: Elastic (superseded)
**Date:** 2026-05-23  
**Superseded by:** D-001  
**Original rationale:** Elastic framed as "retrieval-driven operational intelligence" — semantic search over media assets and historical campaign data  
**Why it didn't hold:** Gemini handles the actual reasoning. Elastic's role was one `search_assets` call with synthetic seeded data. MCP was decorative, not load-bearing.

---

### D-002 — Core Intelligence Layer
**Date:** 2026-05-23  
**Decision:** Commercial moment detection via vector search over historical performance — not virality prediction  
**Rationale:** Virality prediction is pseudoscientific and unvalidatable in a hackathon demo. "Operationalizes historically correlated signals" is more credible and more defensible to judges. Vector search over past campaign performance grounds scoring in actual data.

---

### D-003 — MVP Scope Constraints
**Date:** 2026-05-23  
**Decision:** Hard limits enforced  
- One event type: World Cup soccer  
- Social: simulated (superseded "TBD: Instagram" — see D-007)
- One ecommerce system: Shopify  
- Product types: poster, t-shirt (2 max)  
- Human approval required before any execution  
**Rationale:** Scope creep kills hackathon projects. Narrow enough to finish; wide enough to demonstrate full workflow.

---

### D-005 — Agent Runtime: Google ADK v2.1 + Cloud Run (updated by D-011)
**Date:** 2026-05-23 (updated 2026-05-23)  
**Decision:** Google ADK v2.1 for agent orchestration and state machine; hosted on Cloud Run  
**Ruled out:** Google Cloud Agent Builder (limited MCP client control); LangChain + LangGraph (initially chosen, superseded after spike confirmed ADK viability)

**Reasoning:**
- Spike (D-011) confirmed ADK v2.1 HITL suspend/resume works correctly — both pass criteria met
- ADK has native `McpToolset` built-in — no external adapter needed vs. `langchain-mcp-adapters`
- Google ADK on a Google Cloud hackathon is a genuine optics advantage — judges are GCP engineers
- LangChain remains a valid fallback if ADK hits unexpected issues in implementation
- Cloud Run is the natural hosting target for Python agent backends (listed in spec for custom backends)
- Model: `gemini-2.5-flash-lite` (confirmed working; `gemini-2.0-flash` deprecated for new users)

---

### D-006 — Vector Embedding Provider: Gemini `gemini-embedding-2`
**Date:** 2026-05-23  
**Decision:** Gemini `gemini-embedding-2` via Vertex AI  
**Ruled out:** Voyage AI `voyage-multimodal-3.5`

**Reasoning:**
- Voyage AI is a separate AI company — not a "built-in feature" of MongoDB, just a recommended pairing. Falls under "all other AI tools not permitted" in the hackathon rules. Real compliance exposure, not worth it.
- `gemini-embedding-2` is 3072 dimensions (vs. Voyage's 1024 default) — higher semantic precision for image similarity
- Same GCP credential chain as the rest of the stack — no separate API key or billing account
- One less service dependency on a 19-day timeline

---

### D-011 — ADK v2.1 Spike: PASS — switch to ADK
**Date:** 2026-05-23  
**Decision:** Google ADK v2.1 confirmed viable; supersedes LangGraph (D-005 updated)

**Spike results** (`spike/adk_hitl_test.py`):
- HITL suspended correctly: **PASS** — `LongRunningFunctionTool` emitted `long_running_tool_ids`, runner suspended
- HITL resumed correctly: **PASS** — `FunctionResponse` resume worked, agent produced coherent final response
- Model: `gemini-2.5-flash-lite` (required — `gemini-2.0-flash` deprecated for new API users)

**Notes:**
- `McpToolset` is built into ADK — cleaner than `langchain-mcp-adapters`
- OTel context warning on generator exit is cosmetic noise, not a functional issue
- LangGraph remains a documented fallback if implementation hits ADK-specific blockers

---

### D-010 — Demo Assets: Wikimedia Commons
**Date:** 2026-05-23  
**Decision:** Source 20–50 freely licensed soccer/sports photos from Wikimedia Commons  
**Ruled out:** Unsplash (license requires attribution, restricts competing with Unsplash); Gemini image generation (adds infrastructure complexity, generated images look artificial)

**Reasoning:**
- Wikimedia Commons has large collections of freely licensed sports/soccer photos (CC BY-SA, CC BY) — verifiable licenses, zero API needed
- Download a fixed seed batch for the demo — deterministic, reproducible, no rate limits
- Real photos give the demo more credibility than AI-generated images

---

### D-009 — Print-on-Demand: Printful
**Date:** 2026-05-23  
**Decision:** Printful  
**Ruled out:** Printify (OAuth app registration takes ~1 week; no sandbox)

**Reasoning:**
- Printful: free account, mockup generator API documented, REST-based
- Mockup API is async: `POST /mockups` to create task → `GET /mockups/{task_id}` to poll — fits cleanly into a LangGraph node
- Printify personal token is fast but OAuth registration (needed for proper app integration) takes ~1 week — too slow for this timeline

---

### D-008 — Ecommerce: Shopify Partners Dev Store + GraphQL Admin API
**Date:** 2026-05-23  
**Decision:** Shopify Partners dev store (free), GraphQL Admin API  
**Ruled out:** Real paid store (unnecessary cost and overhead for a demo)

**Reasoning:**
- Shopify Partners account is free, provides unlimited development stores
- Dev stores support full Admin API access — confirmed by Shopify's own docs using `.myshopify.com` in examples
- REST API for products deprecated as of 2024-04 — use GraphQL Admin API
- Requires `products` access scope; draft orders also supported

---

### D-007 — Social Platform: Simulated (no live API)
**Date:** 2026-05-23  
**Decision:** Simulate social post step — no live platform API  
**Ruled out:** Instagram (Meta app review required for posting to other accounts; setup friction fragile for demo); X/Twitter (API docs return 402 Payment Required — paywalled write access)

**Reasoning:**
- The demo value is in orchestration, not whether pixels appear on a live feed
- Agent creates a complete post package: image, caption, hashtags, optimal timing → writes to MongoDB with `status: "ready_to_publish"` → marked `status: "queued"` after human approval
- This is more honest to the HITL workflow: human approves the post content, system queues it
- Eliminates the riskiest external dependency from the demo path

---

### D-004 — Project Positioning
**Date:** 2026-05-23  
**Decision:** "Real-time event commerce operations agent" — not "AI for creators," not "AI photo sorter," not "AI marketing platform"  
**Rationale:** Operational framing sounds enterprise-capable and differentiates from commodity content tools. Judges need to see a workflow system, not a content optimizer.

---

## Open Questions

All resolved. See decision log D-005 through D-010.

---

## Next Actions

- [x] Choose agent runtime — **LangChain + LangGraph + Cloud Run** (D-005)
- [ ] Provision MongoDB Atlas cluster + configure MCP server
- [ ] Design the 5 collection schemas (events, assets, campaigns, approvals, performance)
- [ ] Seed `performance` collection with synthetic historical campaign data for vector search to work on day one
- [ ] Scaffold the 8-step agent loop in chosen runtime
- [ ] Wire first end-to-end path: ingest → score → approval queue (no execution yet)
- [ ] Add execution layer: Shopify draft creation
- [ ] Add execution layer: Printful product job
- [ ] Build approval UI (minimal — could be CLI or simple web form)
- [ ] Record demo video
- [ ] Host project
- [ ] Submit to Devpost before June 11

---

## Planning Document Index

| File | Role | Status |
|------|------|--------|
| `rapid_agent_hackathon_spec.md` | Hackathon rules, partner details, judging criteria | Reference — do not modify |
| `Project Concept.md` | Original concept and demo flow | Superseded by docs/specs/ |
| `Real-Time Event Commerce Operations Agent (MCP-Orchestrated).md` | Executive summary, problem statement | Superseded by docs/specs/ |
| `operational orchestration infrastructure.md` | Partner analysis (concluded Elastic) | Superseded by D-001 |
| `aesthetic optimization.md` | Key reframe: commercial intent vs. aesthetics | Superseded by docs/specs/ |
| `"Autonomous fan-content monetization and distribution pipeline.".md` | Earliest concept iteration | Historical only |
| `CLAUDE.md` | **Index — see docs/specs/ for spec files** | Current |
| `docs/specs/00-overview.md` | **Vision, origin, positioning, demo narrative** | Current |
| `docs/specs/01-requirements.md` | **Functional spec, 8-step workflow, MVP scope** | Current |
| `docs/specs/02-architecture.md` | **System design, schemas, MCP call list** | Current |
| `tracking.md` | **This file — decision log and task tracker** | Current |
