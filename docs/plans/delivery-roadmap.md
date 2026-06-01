# Delivery Roadmap — Back Third

**Deadline: June 11, 2026 @ 2:00 PM PDT**  
**Today: May 30, 2026 — 12 days.**

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
- 40 assets with **real `gemini-embedding-2` embeddings** (fetched from Wikimedia URLs at seed time) — the vector search works against these
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

3. **Verify pool composition**: run `find_similar_assets` against both batches against the live seeded Atlas corpus. Confirm Event 1 produces ~6–8 exploitation candidates and Event 2 produces ~2–3. Swap images if the contrast isn't there — the seeded corpus is fixed, only the demo batch changes.

4. **Adjust if needed**: if the contrast isn't strong enough, swap images and re-verify. The seeded corpus is fixed — only the demo batch images change.

### Source

Wikimedia Commons, CC-licensed. Safe for demo and submission (hackathon requires open-source, judges may inspect).

---

## Track 2 — Approval UI (Next.js)

**Goal:** a standalone Next.js app that renders the Step 7 HITL approval batch and submits the `approval_id`-keyed decisions list. Buildable 80% to hi-fi on pure mock data; wired to real backend in one swap before demo recording.

### Phase A — mock-first (start now, no corpus dependency)

| Item | Detail |
|------|--------|
| Stack | Next.js (App Router), Tailwind CSS |
| Data | JSON fixture matching the Step 7 approval batch shape (hardcoded, ~10 assets across 2 channels) |
| Images | 5–6 placeholder images (Wikimedia grabs or Lorem Picsum) |
| Interactions | Per-asset: approve / reject / request-edit with note field; submit sends decisions to console or stub endpoint |
| Contract | `approval_id`-keyed decisions list — shape frozen by Step 7 (`src/db/approvals.py`) |

**Key UI beats the demo must show:**
- Grouped display: assets batched by channel (shopify / social)
- Per-item AI reasoning text visible inline (the throughline per `00-overview.md`)
- Approve/reject/edit controls per asset
- Submit posts the structured decisions list

### Phase B — wire to real backend (after corpus lands)

- Swap fixture for a fetch from the coordinator's approval endpoint
- Point submit POST at the real `FunctionResponse` handler
- Confirm round-trip: UI decisions → MongoDB `approvals` collection → `execute_approved_campaigns` reads them

**Open items:**
- Hosting for the UI during the demo: local (`next dev`) or deploy alongside Cloud Run?
- Auth / session: none needed for demo (single operator, no multi-user)

---

## Track 3 — Live Wiring

**Goal:** swap the four stubbed Shopify/Printful helper bodies (Step 7 Option-1 deferral) for real API calls. Produces the live `mockup_url` demo artifact — the key commercial proof point.

The four stubs are in `src/capabilities/execution.py` (or equivalent Step 7 execution helpers). Exact function names TBD on inspection.

| Stub | Real call |
|------|-----------|
| Shopify product create | Shopify GraphQL Admin API — `productCreate` mutation |
| Shopify variant/listing | Shopify GraphQL Admin API — variant + publication |
| Printful mockup | Printful REST API — mockup generation task + poll |
| Social post | Remains simulated (Hard Constraint #6) |

**Dependency:** corpus must exist (need real `asset_id`s and image URLs to test against live APIs).

**Open items:**
- Confirm Shopify Partners dev store credentials are in `.env`
- Confirm Printful API key is in `.env`
- Printful mockup generation is async (task + poll) — decide whether to poll inline or fire-and-forget for demo purposes

### Preview-before-publish (credential-gated) — what makes "judges can run it" true

**Why:** a judge brings a MongoDB URI + Google auth, not a Shopify Partner store or a Printful key. With no credential-free path, the agent's payoff artifacts (product page, mockup) are invisible to anyone running it themselves. So each channel gets a **real path and a labeled preview path, selected by credential presence** (`SHOPIFY_*` / `PRINTFUL_*` env) — generalizing how social is already simulated (Hard Constraint #6).

**Frame it as a feature, not a fallback:** preview-before-publish is the *content of the HITL approval gate* — the operator reviews the rendered artifacts, then approves. With live keys, approval publishes for real; without, it stays preview. Same artifacts either way.

**Honesty rule (D-032 ethos):** preview artifacts must be labeled "Preview · live Shopify/Printful not configured" — never dressed up as a real published product. Honest, and more impressive for showing you know the difference.

**Per-channel cost:**
- Shopify preview — cheap: synth `product_id` + `product_url` + title/price (≈ today's stub, dressed up).
- Printful preview — the only real-cost bit: its value *is* the rendered mockup. Start with a clean labeled placeholder/template frame; compositing the asset onto a poster/tshirt template is optional polish, not required.
- Social — already simulated.

**Schedule win:** preview decouples the on-camera demo path from live API credentials the same way the UI is decoupled from corpus — the full flow runs end-to-end with zero ecommerce credentials. Live keys become an enhancement, not a blocker.

**MANDATORY — do not repeat the MCP "never tested the real path" trap.** If preview becomes the default demo path, the *real* Shopify/Printful code is at risk of never being exercised — exactly what happened to the MCP read path (mock-only-validated, actually broken against the real server until 2026-05-31). Pick one, deliberately:
1. Capture at least one **live run** of the real path (à la `scripts/capture_mcp_fixtures.py` / the vendored-bin probe) to prove it works and record the real artifact shapes; **or**
2. Explicitly accept preview-only for the submission and say so plainly in the demo video.
The partner integration that *must* be real is **MongoDB MCP** (done) — Shopify/Printful are the agent's *actions*, so a labeled preview is defensible. But the choice must be deliberate, not an accident of having only tested the mock.

**Phase A/B split (pairs with Track 2):**
- **Phase A (now, `ui/phase-a`):** build the preview *cards* (Shopify product preview, Printful mockup frame) against mock data — same move as the social-post mock. They become the visual contract for the Phase-B preview generators.
- **Phase B:** the credential-gated real/preview fork at the execution seam; the UI cards consume real-or-preview output with no change.

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

| Day | Focus |
|-----|-------|
| May 30–31 | Approval UI Phase A (Next.js scaffold, mock fixtures, full interaction flow) |
| Jun 1–2 | Demo corpus: curate images, `prep_demo_corpus.py`, verify similarity contrast; close hygiene |
| Jun 3–4 | `src/api/` FastAPI bridge; Approval UI Phase B wire-up; live wiring (Shopify/Printful) |
| Jun 5–6 | End-to-end smoke test on localhost (both events, redraft path) |
| Jun 7–8 | Demo dry runs; fix anything broken |
| Jun 9 | Record demo video (localhost) |
| Jun 10 | Cloud Run deploy + session service swap; Devpost submission draft |
| Jun 11 | Submit before 2:00 PM PDT |
