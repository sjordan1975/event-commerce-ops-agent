# Approval UI — Operator Console Spec

This document defines the operator console: the primary demo artifact and the interface through which a judge experiences the full agent workflow. It is not just an approval widget — it is the screen that has to be on camera for the entire 3-minute demo video.

**Related docs:** `docs/plans/delivery-roadmap.md`, `docs/specs/01-requirements.md` § Demo Flow, `docs/specs/00-overview.md` § Demo Narrative, `docs/specs/02-architecture.md` (capability contracts).

---

## What this UI must do

1. Accept a natural-language kickoff message and start the agent pipeline
2. Show the workflow making progress — capability by capability — with operator-legible labels and real-time status
3. Surface the full approval batch with per-asset reasoning, score profiles, and channel routing at the HITL gate
4. Accept approve / reject / edit-request decisions per asset and submit them
5. Show execution evidence: Shopify product, Printful mockup, mocked social post — **real when credentials are configured, labeled preview otherwise**
6. Handle the redraft loop if any item is edit-requested
7. Show a final MongoDB state summary after completion
8. Show live **MongoDB MCP connection health** — the load-bearing partner integration made visible and honest

It must look polished enough to appear in a demo video watched by competition judges. "Clean and functional" is not the bar — the visual quality is a judging criterion (`01-requirements.md` § Judging Criteria: "Design").

---

## Layout

Desktop-only. Dark theme throughout — near-black background (`#0A0A0A`), aesthetic reference is Antigravity.

Two columns, header at top. Left column is **full height**. Right column splits vertically: activity + content pane on top, chat input anchored to the lower-right pane.

```text
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
│  ──────────────────────  │                                              │
│  ● MongoDB MCP · 43 tools│                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
```

**Left column — streaming notices (full height, ~35%):** real-time read-only feed of agent events — capability completions, reasoning excerpts, coordinator decisions. Each entry is a compact card: icon + label + one-line summary. No interaction. Older entries scroll up and fade; most recent 6–8 visible. Pinned to the **bottom** of this column, below a divider, is the persistent **MCP health badge** (`McpHealthBadge`) — full spec in § MCP connection health.

**Right column top — activity + content (~65%, upper ~70% of right column):** activity timeline (deterministic capability checklist, spinner → checkmark) at the top. Dynamic content zone below it — transitions between idle / approval batch / evidence / final summary as phases progress.

**Right column bottom — chat input (lower ~30% of right column):** the kickoff message, clarification exchange, and any mid-run commands. Centered within this zone. Rounded border, dark fill, subtle glow on focus. No model selector (coordinator model is server-configured, not operator-chosen). No attach control — the demo images are pre-downloaded to known local paths on the demo machine before recording; the operator references the directory path in the chat message (`"Photos at /tmp/wc-final/"`), the coordinator enumerates the directory and passes the file list to `ingest_event_batch`. No real-time upload through the UI is needed or architecturally coherent with how `ingest_event_batch` works (it takes `list[str]` paths/URLs and stores them as `content_url` — the agent server reads from those paths directly).

**Demo environment: localhost.** The demo video is recorded locally; `/tmp/wc-final/` resolves on the same machine as the agent server. On Cloud Run, images must be pre-staged in GCS and the operator references a `gs://` path instead — `ingest_event_batch` enumerates the bucket and stores `gs://` URIs as `content_url`, which Vertex AI reads natively.

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

**Social panel** — per-post cards, each opening a full Instagram-style preview.
```
┌─────────────────────────────────────────────────────────┐
│  SOCIAL QUEUE — 4 POSTS                                 │
│  ┌──────────────────────────────────────────────┐      │
│  │  [photo]  Argentina's Miracle...             │      │
│  │           #WCFinal #ArgentinaVsFrance        │      │
│  │           ● queued in atlas                  │      │
│  │           ↗ View mock                        │      │
│  └──────────────────────────────────────────────┘      │
│  ... (3 more post cards)                               │
└─────────────────────────────────────────────────────────┘
```

Social posting is simulated (Hard Constraint #6) — but the UI does **not** stop at a text card. Each card carries the "queued in atlas" badge **and a `View mock` button** that opens a full **Instagram-style post preview** (`SocialPostMock` — a modal portaled to `document.body`): profile row (`fieldhouse · Sponsored`), square photo, like / comment / share / bookmark row, a likes count, the caption prefixed with the `fieldhouse` handle, hashtags in Instagram blue, and a relative timestamp.

```
┌────────────────────────────┐
│  ● fieldhouse · Sponsored ⋯│
│  ┌──────────────────────┐  │
│  │    [ square photo ]  │  │
│  └──────────────────────┘  │
│  ♡   ◯   ➤            ⤓    │
│  1,247 likes               │
│  fieldhouse  Argentina's…  │
│  #WCFinal #ArgentinaVsF…   │
│  2 MINUTES AGO             │
└────────────────────────────┘
```

This "what it would look like published" preview is the **same preview-before-publish pattern** the Shopify/Printful cards adopt below (§ Preview mode) — social just happens to always be in preview (no live platform API, ever).

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

**Preview mode (no live Shopify/Printful credentials).** *(Build status: COMPLETE — Phase A, `ui/phase-a`.)* The evidence section has two modes, selected by whether `SHOPIFY_*` / `PRINTFUL_*` credentials are configured on the backend — carried as `mode: 'live' | 'preview'` on `ExecutionEvidence` (in `lib/types.ts`). **Preview is the default a judge sees** (they run the project with a MongoDB URI + Google auth, not an ecommerce store), and it is also the content of the approval gate — "what would be published." Same card structure as live, two differences:

1. A **`PreviewBadge`** on each Shopify/Printful card: `Preview · live Shopify/Printful not configured`. Never present a preview as a real published product (D-032 honesty ethos).
2. Artifacts are synthesized, not fetched: Shopify gets a plausible `product_id` + product-style URL (non-navigating, or a local preview route); the `ShopifyCard` **mockup thumbnail** (its existing async image slot) shows the asset on a poster/t-shirt template — Phase A a clean labeled placeholder; real compositing is optional polish. Like the social card, a Shopify preview card may also offer a `View mock` expansion — the same card → rich-modal pattern as `SocialPostMock`.

```
┌─────────────────────────────────────────────────────────┐
│  SHOPIFY PRODUCT · PREVIEW                              │
│  ⚠ Preview · live Shopify/Printful not configured      │
│  "Argentina's Miracle — Match-Worn Moment"             │
│  product ID: preview-#1234567      $34.00              │
│  ┌───────────────┐                                     │
│  │  [ poster     │  ← Printful mockup frame            │
│  │    mockup     │     (asset on a poster template;    │
│  │    preview ]  │      labeled placeholder Phase A)   │
│  └───────────────┘                                     │
└─────────────────────────────────────────────────────────┘
```

Social is already preview/simulated in both modes (Hard Constraint #6) — no `mode` difference there.

**Phase A (delivered):** evidence renders in preview mode (`mode: "preview"` in fixture). `ShopifyProduct` carries a `photoUrl` (source photo, shown in the 100×100 thumbnail) separate from `mockupUrl` (the product mock, opened via "View mock"). T-shirt mockups are AI-generated offline via `spike/gemini_tshirt_mockup.py` (Gemini 3 Pro image) and stored as static assets in `ui/public/mockups/`. Poster mockups use the source photo rendered in a white print frame.

**Phase B:** the credential-gated real/preview fork lives at the execution seam in `src/api`; the cards consume `mode` + the same shapes with no change. **Phase B mockup generation:** even in preview mode (no Printful creds), the real pipeline needs real-time mockup generation — this must live server-side in `src/api` with retry logic. Pre-generated statics are a demo-day safety net only; Phase B generates live from approved assets. See delivery-roadmap Track 3 for the full strategy. **Mandatory: exercise the real Shopify/Printful path at least once, or state preview-only in the video.**

---

### Beat 5 — Event 2 transition

After Event 1 completes, a divider appears in the right column: `── Event 2: Germany vs. Spain 1–1 · Group stage draw ──`

The chat input is available again. The activity timeline begins a new block below the divider. The demo shows the contrast: thin exploitation queue, exploration emphasis, different per-item reasoning. Pacing is ~45 seconds (skip-ahead on ingest/score, focus on queue assembly and the approval batch differences).

---

## MCP connection health (persistent)

> **Build status: COMPLETE (Phase A, `ui/phase-a`).** `McpHealthBadge` and `McpHealthDetail` (popover) are live in `ui/src/components/McpHealthBadge.tsx`. Driven by mock health state; Phase B swaps to `/health` poll.

Persistent across every phase — pinned to the **bottom of the left column**, below a divider under the streaming notices, visible even on the landing state. This is the visualization of the load-bearing partner integration: the demo's standing proof the agent is talking to a real MongoDB MCP server, not a fake.

**Collapsed (default):** one compact row — colored status dot + `MongoDB MCP` + tool count.

```
● MongoDB MCP · 43 tools
```

**Expanded (hover or click):** a small popover with the full signal set.

```
┌──────────────────────────────────┐
│  ● MongoDB MCP — connected       │
│  ──────────────────────────────  │
│  Tools discovered      43        │
│  Last successful call  2s ago    │
│  Reconnect attempts    0         │
│  Server version        1.11.0    │
└──────────────────────────────────┘
```

**States (honest degradation — load-bearing, not decoration):**

| State | Dot | Meaning |
|---|---|---|
| `connected` | green | session live, tools discovered, recent successful call |
| `reconnecting` | amber, pulsing | session dropped; background reconnect running; requests degrade |
| `unavailable` | red | no session / `warm()` failed; the agent cannot reach Atlas |

The widget must reflect **true** state. A permanently-green indicator is theatre that undoes the "health separate from request handling" principle (D-035) — red when the session is actually down is the entire point. On `unavailable`, the expanded view shows the error string from `/health`.

**Data source — a poll, not SSE.** A status light needs no event stream; poll `GET /health` every ~5s (contract in § Real-time data contract). Today `/health` returns only `{mcp_ready, mcp_error}`; the richer payload (`status`, `tools_discovered`, `last_successful_call`, `reconnect_attempts`, `server_version`) is Phase-B connection-manager work — design in `docs/plans/mcp-connection-lifecycle.md` § Health surface in the UI / D-035.

**Phase A (delivered):** boot sequence runs on mount: `unavailable` (red) → `reconnecting` (amber, pulsing) at ~1.4s → `connected` (green, 43 tools) at ~3.1s. Event1 fixture scripts a mid-pipeline `reconnecting → connected` blip (~4.8s into the run) proving all three states render live. Event2 has no blip. Health transitions are defined in `mcp_health_transitions` arrays in the fixture files. **Phase B:** swap the mock object for the `/health` poll; UI unchanged — the shape is the contract.

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
| `ShopifyCard` | Inside EvidenceSection | Product type, title, "View on Shopify" link, `Draft · {productId}`; mockup thumbnail (spinner → image; labeled placeholder in preview mode) |
| `SocialPostCard` | Inside EvidenceSection | Photo, copy, hashtags, "queued in atlas" badge, **`View mock` button** |
| `SocialPostMock` | Inside EvidenceSection (modal, portaled to `document.body`) | Instagram-style post preview — profile row, square photo, action row, likes count, caption, hashtags, timestamp |
| `AtlasStatePanel` | Inside EvidenceSection | Collection row counts — events/assets/campaigns + approvals & performance breakdowns |
| `EventDivider` | Right column | Visual separator between Event 1 and Event 2 blocks |
| `ChatBar` | Right column, lower pane | Centered input with conversation history above; rounded dark styling; no model selector, no attach control |
| `McpHealthBadge` | Left column, pinned bottom | Persistent MCP status — dot + "MongoDB MCP" + tool count; honest 3-state (connected / reconnecting / unavailable) |
| `McpHealthDetail` | Popover from `McpHealthBadge` | Expanded signals: tools discovered, last successful call, reconnect attempts, server version, error |
| `PreviewBadge` | Inside `ShopifyCard` | "Preview · live not configured" label when evidence `mode` is `preview` (net-new — not in current `lib/types.ts`) |

---

## Real-time data contract (Phase B — wire-up)

> **Shapes live in `ui/src/lib/types.ts` — that is the single source of truth.** This section specifies only the SSE *envelope*: the event types and which `types.ts` payload each carries. It deliberately does **not** restate field shapes — a spec that duplicates the types drifts from them (precisely the snake_case/`event_id`-here vs. camelCase-domain-types-there divergence that prompted this rewrite). When the wire format is built, evolve `types.ts`, never a parallel list here.

The backend emits a Server-Sent Events (SSE) stream; the UI consumes it. Each event is `{ type, payload }`, payloads referencing `lib/types.ts`:

| SSE `type` | Payload (→ `lib/types.ts`) | Notes |
|---|---|---|
| `capability_started` | `{ capability: Capability, eventId }` | `ActivityTimeline` row → running |
| `capability_completed` | `{ capability: Capability, resultSummary, strategyExcerpt? }` | row → complete; `strategyExcerpt` drives the `QueueAssemblyRow` |
| `coordinator_message` | `ChatMessage` | thread entry (coordinator / operator) |
| `approval_ready` | `{ approvalId, items: ApprovalItem[] }` | opens `ApprovalBatch` |
| `execution_evidence` | `ExecutionEvidence` + `mode: 'live' \| 'preview'` *(net-new)* | opens `EvidenceSection` |
| `mockup_resolved` | `{ assetId, mockupUrl }` | async; merged into the `mockupUrls: Record<assetId,url>` map `EvidenceSection` consumes |
| `atlas_state` | `AtlasState` | **structured** (approvals/performance breakdowns), not a flat count map |
| `pipeline_complete` | `{ eventId }` | terminal |

**Two shape facts the wire format must honor (both already true in the code):** Atlas state is the *structured* `AtlasState`, not `Record<string,number>`; and mockups arrive *after* `execution_evidence` and are merged by `assetId` into the `mockupUrls` map, not embedded in the evidence payload. Fixtures are snake_case (`FixtureShopifyProduct` etc.) and mapped to the camelCase domain types in `mock-api.ts`; the wire format should target the **domain** types, and that mapping layer can absorb whatever casing the backend emits.

The operator's kickoff message and approval decisions are POST requests; SSE is read-only from the UI side.

**Health (polled, not SSE):** the MCP health badge polls `GET /health` every ~5s — a status light needs no stream.

```typescript
// GET /health — polled ~5s
{
  status: "connected" | "reconnecting" | "unavailable",
  mcp_ready: boolean,
  tools_discovered: number,             // 43
  last_successful_call: string | null,  // ISO 8601
  reconnect_attempts: number,
  server_version: string,               // "1.11.0"
  error: string | null,
}
```

The current backend returns only `{ mcp_ready, mcp_error }`; the rest is Phase-B connection-manager work (`mcp-connection-lifecycle.md` / D-035).

---

## Mock data strategy — Phase A

Build the full UI against a JSON fixture. No backend dependency. Capability progression is simulated with `setTimeout` delays (600–1800ms per step — fast enough to feel live, slow enough to read).

**Fixture file:** `ui/src/mock/event1.json`

Fixture must include:
- Event metadata (name, `outcome_type`, timeliness label)
- Coordinator message thread (4–6 messages simulating clarification + progress commentary)
- 8 approval items, pre-populated: photo URL, channel routing, copy draft, agent reasoning text, 5-dimension scores
  - 4 Shopify items (mix of `poster` and `tshirt`)
  - 4 social-only items
  - At least 1 pre-marked `edit_requested` to exercise the redraft path
- Execution evidence: Shopify product stubs (with placeholder URL), social post cards, Atlas collection counts — rendered in **preview mode** (`mode: "preview"`, `PreviewBadge`, Printful placeholder frame); the fixture carries no credentials
- Mock **MCP health** object: `status`, `tools_discovered`, `last_successful_call`, `reconnect_attempts`, `server_version` — drives `McpHealthBadge`; optionally script a brief `reconnecting → connected` blip so the degraded state is proven to render

**Image placeholders:** 8 CC-licensed Wikimedia Commons soccer photos confirmed for Phase A. Use these in fixtures; swap for real corpus images in Phase B.

| URL | Subject | License |
|-----|---------|---------|
| `https://upload.wikimedia.org/wikipedia/commons/1/1a/Argentina_vs_France_2018_World_Cup_22.jpg` | Argentina vs France 2018 WC — match action | CC BY 4.0 |
| `https://upload.wikimedia.org/wikipedia/commons/b/b8/Argentina_vs_France_2018_World_Cup_34.jpg` | Argentina vs France 2018 WC — match action | CC BY 4.0 |
| `https://upload.wikimedia.org/wikipedia/commons/b/b8/Messi_vs_Nigeria_2018.jpg` | Messi celebrating vs Nigeria 2018 WC | CC BY-SA 3.0 |
| `https://upload.wikimedia.org/wikipedia/commons/e/e5/Kylian_Mbapp%C3%A9_2018.jpg` | Mbappé, Best Young Player 2018 WC | CC BY-SA 3.0 |
| `https://upload.wikimedia.org/wikipedia/commons/e/e6/Iran_vs_Portugal_2018_FIFA_World_Cup_%282%29.jpg` | Iran vs Portugal 2018 WC — match action | CC BY-SA 3.0 |
| `https://upload.wikimedia.org/wikipedia/commons/2/2e/Argentina_3-3_Francia_-_Copa_Mundial_2022_-_Celebraci%C3%B3n_de_victoria.jpg` | Argentina 2022 WC victory celebration | CC BY 3.0 |
| `https://upload.wikimedia.org/wikipedia/commons/5/56/Mario_G%C3%B6tze_GOL_-_The_2014_FIFA_World_Cup_Final_-_140713-9112-jikatu_%2814463413827%29.jpg` | Mario Götze goal, 2014 WC Final (event2) | CC BY-SA 2.0 |
| `https://upload.wikimedia.org/wikipedia/commons/7/74/Football_%28Soccer%29.JPG` | Generic soccer match action (event2) | CC BY-SA 4.0 |

**Event 2 fixture:** `ui/src/mock/event2.json` — thinner queue (5 items total), higher proportion of exploration picks, different reasoning text to show the contrast.

**Phase A gate — COMPLETE (`ui/phase-a`):**
- ✓ Full journey from kickoff message through execution evidence is playable end-to-end
- ✓ Redraft loop exercises correctly (edit-requested item flows through re-approval)
- ✓ Both events are navigable
- ✓ No layout breaks with 4-item vs. 8-item queues
- ✓ Printful mockup "resolution" (spinner → image) simulated with 2s delayed swap
- ✓ MCP health badge visible from landing state; boot sequence red→amber→green; mid-pipeline blip in Event 1
- ✓ Preview cards: `PreviewBadge`, source photo thumbnails, "View mock" lightbox (poster frame + AI t-shirt)
- ✓ AI t-shirt mockups pre-generated (`spike/gemini_tshirt_mockup.py`, Gemini 3 Pro image, stored in `ui/public/mockups/`)

---

## Phase B wire-up plan

One-afternoon swap once backend + corpus are ready:

1. Replace fixture fetch with SSE connection to coordinator endpoint
2. Remove `setTimeout` simulation; capability rows now driven by `capability_started` / `capability_completed` events
3. Replace placeholder image URLs with real Atlas asset URLs
4. Wire approval submit POST to real `FunctionResponse` handler
5. Wire mockup resolved to `mockup_resolved` SSE event (real async Printful resolution)
6. Verify Atlas state panel against real collection counts
7. Poll real `GET /health` for the MCP health badge (richer payload from the Phase-B connection manager)
8. Switch execution evidence to the credential-gated `mode`; wire real Shopify/Printful when keys are present — and exercise that real path at least once (Track 3 mandate), don't leave it mock-only

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
| MCP health honesty | Badge reflects true state — green connected, amber reconnecting, red unavailable; never permanently green; expanded view surfaces the error on failure |
| Preview labeling | Preview artifacts carry the `PreviewBadge`; never presented as a real published product |

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
   - MCP health badge (mock health object) + preview-mode evidence cards (`mode: "preview"`, `PreviewBadge`, Printful placeholder frame)
   - Visual polish pass against quality gates above

2. **Phase B — wire-up** (after corpus + backend ready)
   - SSE connection
   - Real approval POST
   - Image URL swap
   - Mockup async resolution
   - `/health` poll for the MCP badge; credential-gated `mode` for evidence (and exercise the real Shopify/Printful path at least once — Track 3 mandate)
   - End-to-end smoke test (both events, redraft path)
