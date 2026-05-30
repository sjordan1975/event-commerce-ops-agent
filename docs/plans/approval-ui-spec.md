# Approval UI — Operator Console Spec

This document defines the operator console: the primary demo artifact and the interface through which a judge experiences the full agent workflow. It is not just an approval widget — it is the screen that has to be on camera for the entire 3-minute demo video.

**Related docs:** `docs/plans/delivery-roadmap.md`, `docs/specs/01-requirements.md` § Demo Flow, `docs/specs/00-overview.md` § Demo Narrative, `docs/specs/02-architecture.md` (capability contracts).

---

## What this UI must do

1. Accept a natural-language kickoff message and start the agent pipeline
2. Show the workflow making progress — capability by capability — with operator-legible labels and real-time status
3. Surface the full approval batch with per-asset reasoning, score profiles, and channel routing at the HITL gate
4. Accept approve / reject / edit-request decisions per asset and submit them
5. Show execution evidence: Shopify product, Printful mockup, mocked social post
6. Handle the redraft loop if any item is edit-requested
7. Show a final MongoDB state summary after completion

It must look polished enough to appear in a demo video watched by competition judges. "Clean and functional" is not the bar — the visual quality is a judging criterion (`01-requirements.md` § Judging Criteria: "Design").

---

## Layout

Desktop-only. Dark theme throughout — near-black background (`#0A0A0A`), aesthetic reference is Antigravity.

Two columns, header at top. Left column is **full height**. Right column splits vertically: activity + content pane on top, chat input anchored to the lower-right pane.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  HEADER — logo · event badge · phase status                             │
├──────────────────────────┬──────────────────────────────────────────────┤
│                          │                                              │
│  STREAMING NOTICES       │  ACTIVITY TIMELINE                          │
│  (left, ~35%, full ht)   │  ─────────────────────────────────────────  │
│                          │  CONTENT PANE                               │
│  Live feed of agent      │  (approval / evidence / summary)            │
│  events as they happen   │                                              │
│                          ├──────────────────────────────────────────────┤
│  Compact notice cards    │                                              │
│  slide in from bottom;   │      ┌──────────────────────────────────┐   │
│  older entries scroll    │      │  Describe an event to begin...   │   │
│  up and fade             │      │                         Send ▶   │   │
│                          │      └──────────────────────────────────┘   │
│                          │                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
```

**Left column — streaming notices (full height, ~35%):** real-time read-only feed of agent events — capability completions, reasoning excerpts, coordinator decisions. Each entry is a compact card: icon + label + one-line summary. No interaction. Older entries scroll up and fade; most recent 6–8 visible.

**Right column top — activity + content (~65%, upper ~70% of right column):** activity timeline (deterministic capability checklist, spinner → checkmark) at the top. Dynamic content zone below it — transitions between idle / approval batch / evidence / final summary as phases progress.

**Right column bottom — chat input (lower ~30% of right column):** the kickoff message, clarification exchange, and any mid-run commands. Centered within this zone. Rounded border, dark fill, subtle glow on focus. No model selector (coordinator model is server-configured, not operator-chosen). No attach control — the demo images are pre-downloaded to known local paths on the demo machine before recording; the operator references the directory path in the chat message (`"Photos at /tmp/wc-final/"`), the coordinator enumerates the directory and passes the file list to `ingest_event_batch`. No real-time upload through the UI is needed or architecturally coherent with how `ingest_event_batch` works (it takes `list[str]` paths/URLs and stores them as `content_url` — the agent server reads from those paths directly).

The operator's sent messages appear above the input in the chat zone (conversation history). Coordinator text responses surface here too. Capability events go to the left streaming column — the two surfaces are distinct.

The layout does not restructure between phases.

---

## The operator journey (beat by beat)

### Beat 0 — Landing state

Left column empty. Right column: activity timeline and content pane are empty; chat input is centered in the lower-right pane with placeholder text *"Describe an event to begin."* — the only interactive element, focus pulled naturally to it.

Header shows: `Fieldhouse · ready`

The emptiness is intentional — both columns fill in once the operator sends the first message. Nothing competes with the chat input on landing.

---

### Beat 1 — Kickoff

Operator types in the chat input:

> Argentina pulled off the upset, beating France 3–2. Photos at /tmp/wc-final/. Match started 19:00 UTC. Ingest this batch.

The operator's message appears in the chat input area (sent state). The first streaming notice slides into the left column. Header transitions to: `Argentina vs. France 3–2 · Ingesting...`

The coordinator may respond with a brief clarifying question before proceeding — that response surfaces as a chat-style message above the input, and the operator replies inline. This exchange is part of the visible story. Coordinator text responses appear in the chat area; capability events go to the left streaming column.

---

### Beat 2 — Workflow in motion

The activity timeline appears in the right column. Rows appear one at a time as each capability starts and completes. Each row has:
- Status indicator: `⟳` spinning (in progress) → `✓` checkmark (done) → `✗` (failed, if applicable)
- Operator-friendly label (see mapping below)
- One-line result summary, populated on completion

**Capability → operator label mapping:**

| Capability | Operator label | Result summary (examples) |
|-----------|----------------|--------------------------|
| `ingest_event_batch` | Batch ingested | 47 photos indexed to Atlas |
| `build_event_context` | Event context built | Upset victory · peak timeliness window · 2 key players identified |
| `find_similar_assets` | Historical matches found | 12 exploitation matches · 3 high-confidence |
| `score_assets_with_vision` | Assets scored | Vision analysis complete · 47 assets |
| `propose_review_queue` | Review queue assembled | 8 items staged · 5 exploitation · 3 exploration |
| `draft_campaigns_for_queue` | Campaign copy drafted | 8 drafts ready · 4 Shopify · 4 social |
| `request_human_approval` | **Awaiting your review** | *(approval section opens — see Beat 3)* |
| `execute_approved_campaigns` | Dispatching to channels | N approved · Shopify + Printful + social |
| `record_outcomes` | Outcomes recorded | Provenance logged · 7-day measurement window open |

**Note on unified labels:** `build_event_context` and `find_similar_assets` run sequentially and both appear as separate rows — they are distinct enough to warrant separate visibility (narrative reasoning vs. vector search). Caps 4 (`score_assets_with_vision`) and 5 (`propose_review_queue`) appear sequentially but are clearly distinct operations.

**Queue assembly row is special.** When `propose_review_queue` completes, the result summary shows more:
- Queue composition: `5 exploitation · 3 exploration`
- One-line coordinator reasoning excerpt (e.g. *"Rich exploitation set this event — similarity engine found 5 strong historical matches. Supplemented with 3 exploration picks: two action shots and one bench moment the model flagged as novel."*)

This is the "strategic-agent moment" per the spec.

---

### Beat 3 — HITL approval gate

When `request_human_approval` starts, the activity timeline row shows `⟳ Awaiting your review` and the dynamic content pane opens the approval section.

**Approval section layout:**

Header bar: `Review queue — 8 items · Event 1 of 2 · Argentina vs. France`

Items grouped by channel:

```
── SHOPIFY (POSTER / T-SHIRT) ─── 4 items ─────────────────────────────────

  ┌─────────────────────────────────────────────────────────────────────┐
  │  [Photo thumbnail]   FILE_0023.jpg · Poster                        │
  │                      ─────────────────────────────────────────────  │
  │                      COPY DRAFT                                     │
  │                      "Argentina's Miracle — Match-Worn Moment"      │
  │                      Historic. Raw. Limited run.                    │
  │                                                                     │
  │                      AGENT REASONING                                │
  │                      Exploitation match — ranked #1 similarity to   │
  │                      past poster revenue leaders. Identity: Messi   │
  │                      backlit. Quality: 4.2/5. Merch score: 0.88.   │
  │                                                                     │
  │  SCORES ░░░░░░░░░░   quality ██████████ 4.2                        │
  │                      emotional ████████░░ 3.9                      │
  │                      social ██████░░░░ 3.1                         │
  │                      merch ████████████ 4.4                        │
  │                      identity ██████████ 4.1                       │
  │                                                                     │
  │  [✓ Approve]  [✗ Reject]  [✏ Request edit]                        │
  └─────────────────────────────────────────────────────────────────────┘

  ... (3 more Shopify items)

── SOCIAL ONLY ─── 4 items ──────────────────────────────────────────────

  ... (4 social items, same card structure)
```

**Edit-request flow:** clicking "Request edit" on an item expands an inline text field: *"Describe what to change..."*. The item enters an `edit_requested` state (amber border, pencil icon).

**Submit control:** a sticky "Submit decisions" button below the queue. Disabled until every item has a decision. Shows a count: `5 approved · 2 rejected · 1 edit requested`.

On submit, the right pane shows an interim state: *"Reviewing decisions..."* while the coordinator processes. If any items are `edit_requested`, a new `⟳ Redrafting N items...` row appears in the activity timeline and the redraft loop begins — approval section re-opens with only the revised items.

---

### Beat 4 — Execution + evidence

When `execute_approved_campaigns` completes, the dynamic content pane transitions to the evidence section.

**Evidence section layout:**

Three panels, one per channel type:

**Shopify panel**
```
┌─────────────────────────────────────────────────────────┐
│  SHOPIFY PRODUCT CREATED                                │
│  "Argentina's Miracle — Match-Worn Moment"              │
│  [View on Shopify ↗]  product ID: #1234567             │
│  Status: Draft · Printful mockup: generating...        │
│                                                         │
│  [thumbnail]  [thumbnail]  ...                         │
└─────────────────────────────────────────────────────────┘
```

When Printful mockup URL resolves, the thumbnail swaps from a spinner to the rendered mockup image. This is a key live artifact for the demo.

**Social panel**
```
┌─────────────────────────────────────────────────────────┐
│  SOCIAL QUEUE — 4 POSTS                                 │
│  ┌──────────────────────────────────────────────┐      │
│  │  [photo]  Argentina's Miracle... #WCFinal    │      │
│  │           #ArgentinaVsFrance #football       │      │
│  │           ● queued in Atlas                  │      │
│  └──────────────────────────────────────────────┘      │
│  ... (3 more post cards)                               │
└─────────────────────────────────────────────────────────┘
```

Social posts are simulated — Hard Constraint #6. The card renders the full copy, hashtags, and a "queued in Atlas" badge. No live platform API.

**MongoDB state panel** (after `record_outcomes`)
```
┌─────────────────────────────────────────────────────────┐
│  ATLAS STATE                                            │
│  events       1 document                               │
│  assets       47 documents                             │
│  campaigns    5 documents  (executed)                  │
│  approvals    8 documents  (5 approved · 2 rejected    │
│                             · 1 edit_requested)        │
│  performance  5 documents  (pending_sync · 7-day       │
│                             window open)               │
└─────────────────────────────────────────────────────────┘
```

---

### Beat 5 — Event 2 transition

After Event 1 completes, a divider appears in the right column: `── Event 2: Germany vs. Spain 1–1 · Group stage draw ──`

The chat input is available again. The activity timeline begins a new block below the divider. The demo shows the contrast: thin exploitation queue, exploration emphasis, different per-item reasoning. Pacing is ~45 seconds (skip-ahead on ingest/score, focus on queue assembly and the approval batch differences).

---

## Component inventory

| Component | Location | Notes |
|-----------|----------|-------|
| `AppShell` | Root | Dark theme, three-zone layout (header / two-column body / chat bar) |
| `EventHeader` | Top bar | Event name, `outcome_type` badge, timeliness indicator, phase label |
| `StreamingNotices` | Left column | Read-only live feed; compact notice cards slide in from bottom, oldest scroll up and fade |
| `NoticeCard` | Inside StreamingNotices | Icon + label + one-line summary; color-coded by capability type |
| `ActivityTimeline` | Right column, top section | Deterministic checklist; rows appear in order with spinner → checkmark |
| `QueueAssemblyRow` | ActivityTimeline row | Expanded row for `propose_review_queue` — shows queue composition + reasoning excerpt |
| `ContentPane` | Right column, below timeline | Dynamic zone; transitions between idle / approval / evidence / summary |
| `ApprovalBatch` | ContentPane phase | Full approval section; appears at HITL gate |
| `AssetCard` | Inside ApprovalBatch | Photo, routing badge, copy draft, reasoning, score bars, decision controls |
| `ScoreBar` | Inside AssetCard | Horizontal bar for each of 5 vision dimensions (0–5 scale) |
| `EditRequestField` | Inside AssetCard | Inline text field, revealed when "Request edit" clicked |
| `SubmitDecisions` | ContentPane, sticky bottom | Disabled until all decisions made; shows live counts |
| `EvidenceSection` | ContentPane phase | Shopify + Social + Atlas panels; appears after execution |
| `ShopifyCard` | Inside EvidenceSection | Product title, URL, mockup thumbnail (resolves async) |
| `SocialPostCard` | Inside EvidenceSection | Photo, copy, hashtags, queued badge |
| `AtlasStatePanel` | Inside EvidenceSection | Collection row counts |
| `EventDivider` | Right column | Visual separator between Event 1 and Event 2 blocks |
| `ChatBar` | Right column, lower pane | Centered input with conversation history above; rounded dark styling; no model selector, no attach control |

---

## Real-time data contract (Phase B — wire-up)

The backend emits a Server-Sent Events (SSE) stream. The UI consumes it. Each event has `type` and `payload`.

**SSE event types:**

```typescript
// Capability started
{ type: "capability_started", payload: { capability: string, event_id: string } }

// Capability completed
{ type: "capability_completed", payload: { capability: string, result_summary: string, event_id: string } }

// Coordinator message (thread entry)
{ type: "coordinator_message", payload: { text: string, role: "coordinator" | "operator" } }

// HITL gate open — approval batch ready
{ type: "approval_ready", payload: { approval_id: string, items: ApprovalItem[], event_id: string } }

// Execution evidence available
{ type: "execution_evidence", payload: { shopify_products: ShopifyProduct[], social_posts: SocialPost[], event_id: string } }

// Printful mockup resolved (async — arrives after execution_evidence)
{ type: "mockup_resolved", payload: { asset_id: string, mockup_url: string } }

// Atlas state snapshot
{ type: "atlas_state", payload: { collection_counts: Record<string, number> } }

// Pipeline complete
{ type: "pipeline_complete", payload: { event_id: string } }
```

The operator's kickoff message and approval decisions are POST requests; SSE is read-only from the UI side.

---

## Mock data strategy — Phase A

Build the full UI against a JSON fixture. No backend dependency. Capability progression is simulated with `setTimeout` delays (600–1800ms per step — fast enough to feel live, slow enough to read).

**Fixture file:** `src/mock/event1.json`

Fixture must include:
- Event metadata (name, `outcome_type`, timeliness label)
- Coordinator message thread (4–6 messages simulating clarification + progress commentary)
- 8 approval items, pre-populated: photo URL, channel routing, copy draft, agent reasoning text, 5-dimension scores
  - 4 Shopify items (mix of `poster` and `tshirt`)
  - 4 social-only items
  - At least 1 pre-marked `edit_requested` to exercise the redraft path
- Execution evidence: Shopify product stubs (with placeholder URL), social post cards, Atlas collection counts

**Image placeholders:** use 6–8 real Wikimedia Commons soccer photos. Manually grabbed URLs, not dynamically fetched. These will be swapped for real corpus images in Phase B.

**Event 2 fixture:** `src/mock/event2.json` — thinner queue (5 items total), higher proportion of exploration picks, different reasoning text to show the contrast.

**Phase A gate (what "done" means for mock-first):**
- Full journey from kickoff message through execution evidence is playable end-to-end
- Redraft loop exercises correctly (edit-requested item flows through re-approval)
- Both events are navigable
- No layout breaks with 4-item vs. 8-item queues
- Printful mockup "resolution" (spinner → image) is simulated with a 2s delayed swap

---

## Phase B wire-up plan

One-afternoon swap once backend + corpus are ready:

1. Replace fixture fetch with SSE connection to coordinator endpoint
2. Remove `setTimeout` simulation; capability rows now driven by `capability_started` / `capability_completed` events
3. Replace placeholder image URLs with real Atlas asset URLs
4. Wire approval submit POST to real `FunctionResponse` handler
5. Wire mockup resolved to `mockup_resolved` SSE event (real async Printful resolution)
6. Verify Atlas state panel against real collection counts

---

## Visual quality gates

These are the bars "polished" means for this project. Each must pass before the UI is demo-ready.

| Gate | What to check |
|------|--------------|
| Typography | Consistent type scale; no raw browser defaults; monospace for IDs and technical values |
| Color + hierarchy | Clear visual hierarchy between primary actions (Approve/Submit) and secondary (Reject, Edit); status colors consistent (green=done, amber=pending/edit, red=rejected) |
| Score bars | 5 bars per asset card, labeled, proportional to 0–5 scale; readable at a glance |
| Reasoning text | Not truncated in the default view; full reasoning visible without a click (this is the throughline per spec) |
| Async mockup swap | Spinner → image swap is smooth; no layout jump |
| Timeline grow | New rows appear with a subtle slide-in; no jarring repaints |
| Empty states | Landing state, post-rejection empty channel group, post-submit waiting state all have intentional designs (not blank divs) |
| Two-event contrast | Event 2's queue visually reads as "thinner" than Event 1 — fewer cards, different badge composition |
| Focus management | After submit, focus moves to the first evidence item; not lost |
| Demo script compatibility | Full Event 1 flow is playable in ≤90s at normal typing speed; Event 2 in ≤45s |

---

## Open decisions

| Decision | Options | Constraint |
|----------|---------|------------|
| Approval UI hosting | `next dev` local during demo vs. Vercel deploy | Local avoids deploy complexity; Vercel avoids "let me start the server" on camera |
| SSE endpoint location | Separate Next.js API route acting as proxy vs. coordinator exposes SSE directly | Next.js API route is simpler for CORS and auth; coordinator is the real source |
| Session threading | How does the UI associate its SSE stream with the right coordinator session (session ID in URL? cookie?) | Must survive the HITL suspend/resume — Cloud Run + session persistence must be resolved first |
| Coordinator thread content | Does the left column show verbatim coordinator output, or a curated subset? | Verbatim may be noisy; curated needs filtering logic |

---

## Build order

1. **Phase A — mock scaffold** (start now)
   - Next.js project init, Tailwind, layout shell
   - Fixture files (event1.json, event2.json)
   - Simulated capability progression (`setTimeout` pipeline)
   - Full component tree through evidence section
   - Visual polish pass against quality gates above

2. **Phase B — wire-up** (after corpus + backend ready)
   - SSE connection
   - Real approval POST
   - Image URL swap
   - Mockup async resolution
   - End-to-end smoke test (both events, redraft path)
