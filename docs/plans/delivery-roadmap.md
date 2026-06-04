# Delivery Roadmap — Back Third

**Deadline: June 11, 2026 @ 2:00 PM PDT**  
**Today: June 2, 2026 — 9 days.**

All 9 agent capabilities are complete on `main`. This document tracks the five delivery/demo-prep tracks that are not capability steps. None touch `src/` agent code except where explicitly noted.

---

## Tracks and dependencies

**Demo video runs on localhost.** Both servers (Python API port 8000, Next.js port 3000) run locally for the recording. `InMemorySessionService` is sufficient — the session lives for the duration of the recording, no restarts. Cloud Run is required for the Devpost submission (hosted URL), but it is NOT on the critical path for the demo video. This removes the hardest dependency from the recording schedule.

```text
Demo Corpus ──────────────────────────────────────────────────┐
                                                               ▼
Approval UI (Next.js, mock-first → wired) ─────────────────► Demo Video
                                                               ▲          (localhost)
Live Wiring (swap 4 stubbed helpers) ─────────────────────────┘

Cloud Run + Session Service ──────────────────────────────────────────► Devpost submission
                                                                         (hosted URL required)

Close Hygiene (dep audit, .env, clone-and-run) ──► parallel, no hard deps
```

**Approval UI is decoupled from corpus** — it starts on mock data immediately and wires to real data in a single swap. This is the key schedule win.

**Cloud Run gates submission, not the video.** Record the demo first, deploy after.

---

## Track 1 — Demo Corpus

**Goal:** two runnable demo events that produce the right agent behavior on camera — Event 1 shows rich exploitation (many similarity matches), Event 2 shows thin exploitation and exploration emphasis. The contrast is the story.

### What already exists

`scripts/seed_mongodb.py` seeds the **historical performance corpus** — the proxy for years of past campaign data that a production system would have accumulated:

- 4 past events, one per `outcome_type`
- 64 assets with **real `gemini-embedding-2` embeddings** (fetched from Wikimedia URLs at seed time) — the vector search works against these
- Scores are **synthetic** (tag-correlated, not live Gemini Vision — that's correct; the seed represents already-scored historical assets)
- Performance metrics are **synthetic** (correlated to scores — also correct; these are past campaign outcomes)

This corpus is already designed and correct. **Do not re-seed it** for demo prep.

### What demo corpus prep adds

The two **demo event batches** — the images the operator will "upload" on camera. These are NOT seeded into Atlas in advance. They are:

1. Downloaded to known local paths on the demo machine before recording
2. Passed to `ingest_event_batch` as local file paths when the operator sends the kickoff message
3. Embedded live by `find_similar_assets`, then vector-searched against the seeded historical corpus

The operator's kickoff message drives everything:
> *"Argentina pulled off the upset, 3–2. Photos at `/tmp/wc-final/`. Match started 19:00 UTC. Ingest this batch."*

The coordinator enumerates `/tmp/wc-final/`, calls `ingest_event_batch(images=[...paths...], event_metadata={...})`. The agent reads the actual files.

### How the demo contrast actually works

`prepare_queue_candidates` makes a mechanical split at the similarity cutoff (default 0.75): assets above go into `exploitation`, assets below go into `discovery`. The LLM receives both pools every time — it orders/reasons about exploitation items and selects/reasons about discovery items. **Both pools are always present for both events.**

The contrast is about **pool composition**, not about switching exploration on or off:

| Event | Exploitation pool | Discovery pool | Why |
|-------|------------------|----------------|-----|
| Event 1 — Upset victory | Large (many assets ≥ 0.75) | Small | Seeded corpus has 2 high-timeliness upset events; celebration/portrait images are visually distinctive and match well |
| Event 2 — Group-stage draw | Small (few assets ≥ 0.75) | Large | Seeded corpus has only 1 draw event; draw imagery is less commercially distinctive, fewer similarity hits at cutoff |

Event 2's agent has more discovery items to reason about and a thinner exploitation set to order — the judgment work is weighted differently, not absent from either pool.

### Image selection strategy — this is the critical design decision

The right pool composition doesn't happen automatically — it requires deliberate image selection. The approach:

1. Probe candidate Wikimedia images against the live seeded corpus embeddings before committing
2. For Event 1: select images where the majority land ≥ 0.75 similarity — celebrations, clean portraits, iconic goal moments that visually echo the seeded `upset_victory` / `extra_time_win` assets
3. For Event 2: select images where most land below 0.75 but a few still hit — more varied compositions, less iconic moments, wider shots — so there's a real but small exploitation pool alongside a larger discovery pool
4. Verify empirically: run `find_similar_assets` on both batches and check the `similar` output before finalising the selection

The target contrast: Event 1 produces ~6–8 exploitation candidates; Event 2 produces ~2–3. Both produce discovery candidates. This makes the per-item reasoning differ visibly between the two events.

### Concrete tasks

1. **Curate candidate images**: browse Wikimedia Commons, select 40–60 candidate soccer photos. Prefer CC-BY or CC-BY-SA. Avoid action shots that could trigger the grounding guard (D-030) — identity/commercial signal (celebrations, portraits, team moments) is safer.

2. **Download to local paths**:
   - `/tmp/wc-final/` — Event 1 images (20–30 files)
   - `/tmp/wc-draw/` — Event 2 images (20–30 files)
   - Write `scripts/prep_demo_corpus.py` with the curated URL list so this is reproducible before any demo run
   - **No duplicates of seed images** — `prep_demo_corpus.py` must assert that none of its URLs appear in `scripts/seed_images.py:SEED_IMAGES` (mechanical guard, not just memory)

3. **Verify pool composition**: run `find_similar_assets` against both batches against the live seeded Atlas corpus. Confirm Event 1 produces ~6–8 exploitation candidates and Event 2 produces ~2–3. Swap images if the contrast isn't there — the seeded corpus is fixed, only the demo batch changes.

4. **Adjust if needed**: if the contrast isn't strong enough, swap images and re-verify. The seeded corpus is fixed — only the demo batch images change.

### Source

Wikimedia Commons, CC-licensed. Safe for demo and submission (hackathon requires open-source, judges may inspect).

---

## Track 2 — Approval UI (Next.js)

**Goal:** a standalone Next.js app that renders the Step 7 HITL approval batch and submits the `approval_id`-keyed decisions list. Buildable 80% to hi-fi on pure mock data; wired to real backend in one swap before demo recording.

### Phase A — COMPLETE (`ui/phase-a`, ~June 2)

Full operator journey is playable end-to-end on mock data. Delivered:

- Dark-theme operator console: two-column layout, streaming notices, activity timeline, content pane, chat bar
- Approval batch: per-asset photo, copy draft, agent reasoning, 5-dimension score bars, approve/reject/edit-request controls, redraft loop
- Evidence section: Shopify product cards + social post cards + Atlas state panel
- **MCP health badge** (persistent, left column): boot sequence red→amber→green on mount; mid-pipeline reconnect blip; click-to-expand detail popover; honest 3-state degradation
- **Preview cards** (`mode: 'live' | 'preview'` on `ExecutionEvidence`): `PreviewBadge` on Shopify cards, source photo thumbnails, "View mock" lightbox — poster = white print frame; t-shirt = AI-generated mockup
- AI t-shirt mockups pre-generated offline via `spike/gemini_tshirt_mockup.py` (Gemini 3 Pro image), stored as static assets in `ui/public/mockups/`; `photo_url` (thumbnail) and `mockup_url` (lightbox) are separate fields on `ShopifyProduct`
- Two fixture events: Event 1 (8-item queue, rich exploitation) and Event 2 (5-item queue, exploration-heavy)

### Phase B — wire to real backend

- Replace SSE simulation with real coordinator SSE stream
- Point submit POST at the real `FunctionResponse` handler
- Replace placeholder image URLs with real Atlas asset URLs
- Wire `mockup_resolved` to real Printful or Gemini (server-side, `src/api`) — see Track 3 for mockup strategy
- Poll real `GET /health` for MCP badge; credential-gated `mode` for evidence section

**Open items:**
- Hosting: local (`next dev`) or deploy alongside Cloud Run?
- Auth / session: none needed for demo (single operator, no multi-user)

---

## Track 3 — Live Wiring

**Status: COMPLETE (D-036)**

Execution stubs replaced with a real end-to-end commerce flow. Printful is not in the execution path.

| Channel | Implementation |
|---------|---------------|
| poster / tshirt | Gemini generates mockup bytes → Shopify `stagedUploadsCreate` → `productCreate` → `productCreateMedia`. Returns `product_url` (admin link) + `mockup_url` (Shopify-hosted image). |
| social_only | Remains simulated — Hard Constraint #6 |

**Credential gate:** with `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET` set, the full live path runs. Without them, Gemini mockup bytes are stored locally in `src/mockup_store` and served at `/api/mockup/{asset_id}` (preview mode). Same code path, credential-switched.

**Verified live:** `scripts/smoke_shopify.py --with-image` confirmed productCreate + staged upload + productCreateMedia on the dev store. Real Shopify admin URL returned. `mockup_resolved` SSE fires inline per item (no deferred post-loop).

---

## Track 4 — Cloud Run Deploy

**Goal:** satisfy the Devpost submission requirement (hosted project URL). The demo video runs on localhost — Cloud Run is NOT on the critical path for recording.

**HITL on Cloud Run — honest assessment:**

The `LongRunningFunctionTool` suspension is a **live async coroutine held in process memory** inside `runner.run_async()`. It is NOT a checkpoint in the session service. This means:

- `DatabaseSessionService` persists conversation history across restarts — good for correctness — but does **not** solve the HITL resumption problem. The suspended coroutine is still process-local regardless of session service.
- If Cloud Run routes the approval POST to a different instance than the one holding the suspended runner, resumption fails.

**Pragmatic answer for submission: single-instance Cloud Run.**

Deploy with `--min-instances=1 --max-instances=1`. One instance, always warm, never scales. Session stays in process memory. If a judge tries the live HITL flow during the submission window, it works as long as the process hasn't restarted mid-session — a reasonable assumption for a short demo session.

`DatabaseSessionService` (MongoDB-backed) is still worth wiring for conversation history persistence and honest partner-track architecture story. It just doesn't change HITL resumption behavior. Swap it in as a polish step.

**Deploy steps (high-level):**

1. Write `Dockerfile` — Python 3.12, `pip install -e ".[dev]"`, entrypoint = `uvicorn src.api.app:app`; include `ui/` build output served by FastAPI as static files (single service, simpler)
2. Deploy to Cloud Run: `--min-instances=1 --max-instances=1`; wire secrets via GCP Secret Manager
3. Smoke-test: confirm UI loads, pipeline starts, approval batch renders (full HITL optional at this stage)

**Open items:**

- GCP project / region confirmed?
- `DatabaseSessionService` implementation: wire before deploy or defer as polish?

---

## Track 5 — Demo Video + Devpost Submission

**Goal:** 3-minute demo video + Devpost submission before June 11 @ 2:00 PM PDT.

**Pacing (from `00-overview.md` § Demo Narrative):**
- Event 1 (~90s): full flow on screen — corpus → pipeline → per-item reasoning → HITL approval UI → execution → `mockup_url` artifact
- Event 2 (~45s): strategic differences only — thin exploitation queue, exploration emphasis, agent justification
- Contrast is the story; per-item reasoning text is the throughline

**Submission requirements (from `docs/plans/step-8-outcomes.md` + hackathon rules):**
- Open-source licensed (confirm `LICENSE` file exists in repo)
- MongoDB as load-bearing MCP partner (demonstrated by Atlas reads/writes throughout)
- Devpost: video link, repo link, written description

**Open items:**
- Screen recording tool decided?
- Devpost account / project stub created?

---

## Close Hygiene

Tracked separately in `docs/project-close-hygiene.md`. Run in parallel — no hard dependency on corpus or UI. Three items:

1. `pyproject.toml` dep audit — promote `google-genai`, `mcp`, `anyio` to explicit pins
2. `.env.example` audit — all env vars documented, required vars marked
3. Clone-and-run verification — clean clone + `pytest` green before submission

---

## Rough order of operations

| Day | Focus | Status |
|-----|-------|--------|
| May 30–Jun 2 | Approval UI Phase A — full console, MCP badge, preview cards, AI t-shirt mockups | ✓ DONE |
| Jun 2–3 | Demo corpus: curate images, `prep_demo_corpus.py`, verify similarity contrast; close hygiene | — |
| Jun 3–5 | `src/api/` FastAPI Phase B wire-up; Approval UI Phase B SSE + real approvals; live wiring (Shopify/Printful); server-side mockup generation | — |
| Jun 6–7 | End-to-end smoke test on localhost (both events, redraft path, MCP badge live) | — |
| Jun 8 | Demo dry runs; fix anything broken | — |
| Jun 9 | Record demo video (localhost) | — |
| Jun 10 | Cloud Run deploy + session service swap; Devpost submission draft | — |
| Jun 11 | Submit before 2:00 PM PDT | — |
