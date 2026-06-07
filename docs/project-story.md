# The Clock Starts When the Whistle Blows

## Inspiration

I'm an avid prosumer photographer. I have well in excess of 30,000 photos on my drives — and if I'm honest with myself, most of them are going to sit there. Not because they're bad. Because getting from "shot" to "done something with it" requires a kind of sustained operational energy that doesn't survive the gap between the moment and the rest of life.

That friction has always nagged at me. What's the point of capturing a moment if it just disappears into an archive?

Then the World Cup started coming into focus, and the question scaled up in a hurry. Thousands of photographers will shoot those matches. Tens of thousands of frames per game. And most of those images will follow the same path mine do — into a folder, then into storage, then into the slow irrelevance of an unprocessed archive.

Except for the ones that don't. The ones that become posters, limited-edition prints, viral posts, the defining visual of a tournament. Those images have something in common with my best shots: the window to do something with them is short, and the bottleneck isn't the photography. It's everything after the shutter closes.

Sports media teams, event photographers, and creator-commerce operators all face the same adversary: the **attention half-life**. Sports moments decay commercially, fast. An iconic goal celebration that could power a limited-edition print run is worth less with every hour that passes. By the time a human team has triaged the batch, scored the assets, drafted copy, gotten approvals, and pushed product listings — the spike is over.

This is not an AI problem. It is a **logistics problem with a time-to-market constraint**.

That framing is what this project is built around.

---

## What it does

**Event Commerce Ops Agent** is an AI-powered commercial logistics coordinator for live event media teams. It takes a batch of post-match photos and a natural-language event description, and orchestrates the full pipeline — from ingestion to published commercial artifacts (Shopify listings and queued social posts) — in under 60 seconds. With a human operator in the loop.

The agent composes nine capabilities:

1. **Ingest** — record the event and bulk-insert all images
2. **Build context** — synthesize an event narrative grounded in historical performance data and player biographies
3. **Find similar assets** — embed each image via `gemini-embedding-2` and run vector search against a corpus of past high-performing assets
4. **Score assets** — run Gemini Vision to score each frame across five commercial dimensions: quality, emotional intensity, social scroll-stop probability, merch suitability, and fan identity signal
5. **Propose the review queue** — the one strategic decision: which assets get surfaced, in what order, with what rationale
6. **Draft campaigns** — generate grounded copy for each queued asset, specific to the event narrative
7. **Request human approval** — HITL gate; nothing executes until the operator signs off
8. **Execute** — Gemini-generated mockup image uploaded to Shopify, product listing created, MongoDB social post queue written
9. **Record outcomes** — write provenance records to feed the next run's similarity search

Every single step makes load-bearing calls to MongoDB Atlas via MCP. Vector search in capability 3 grounds the exploitation path — finding assets that resemble past commercial winners is the mechanical half. The genuinely agentic work is the exploration queue: the agent reasoning about which images that *didn't* match past winners are still worth surfacing, with a one-sentence rationale on every pick. The performance collection is the commercial memory that makes each subsequent event smarter than the last.

The agent is not a content creator. It doesn't claim to predict what will sell. For images that resemble past commercial winners, the answer comes from historical signal — what actually worked before. For images with no precedent to lean on, the model reasons from what it can score in a frame and makes the best case it can to a human who has the final word.

---

## How we built it

The technical stack is Google Cloud end-to-end:

- **Google ADK v2.1** — agent orchestration, HITL via `LongRunningFunctionTool`, graph-wired workflow for deterministic steps
- **Gemini 2.5 Flash** — coordinator reasoning and clarification; `gemini-2.5-flash-lite` for workflow nodes and vision scoring
- **`gemini-embedding-2`** — 3072-dimension multimodal embeddings for image similarity via Vertex AI
- **MongoDB Atlas** — runtime state, vector search corpus, performance collection (commercial memory), approval queue, social queue
- **MongoDB MCP Server** — the transport layer between agent capabilities and Atlas; every capability calls it
- **Shopify GraphQL Admin API** — product listing creation
- **Gemini image generation + Shopify staged upload** — mockup generation and product image attachment via `stagedUploadsCreate` / `productCreateMedia`
- **FastAPI + SSE** — streaming backend; Next.js operator console

The coordinator runs in a chat-mode loop on `gemini-2.5-flash`. The pipeline runs as a graph of `FunctionNode`s (not a `SequentialAgent` — deprecated in ADK v2.1). The coordinator dispatches the workflow via a `FunctionTool` shim that spins up a sub-`Runner` with pre-populated session state. This separation matters: graph orchestration handles deterministic sequencing; the coordinator handles intent, clarification, and the strategic queue assembly decision.

The queue assembly step — capability 5 — is the heart of the system. It operates on two structurally different tracks. **Exploitation**: assets that resemble past high-performers are identified by vector search, and routing is determined by a similarity-weighted plurality vote over historical `product_route` assignments. The LLM cannot override this; the historical signal governs. **Exploration**: assets that didn't match past winners are evaluated by the agent on their own merits — raw vision scores, event narrative, and image content — with a one-sentence rationale attached to each pick. *"This didn't match past winners, but captures the goalkeeper's disbelief in a way the celebration photos don't — worth your time."* This is where the agent earns its keep: judgment without a similarity crutch.

We wrote **254 tests** — 211 unit tests plus scaffolding and live evals — using a three-tier model: unit tests for pure logic; scaffolding tests for prompt structure and output parsing (no LLM calls); trace-based evals for agentic behavior. The eval bar is 95% pass rate across 20 runs per capability.

---

## Challenges we ran into

**MCP session lifecycle.** The MongoDB MCP server, when launched via `npx @latest` in a network-restricted environment, blocks the asyncio event loop during npm registry resolution and hangs indefinitely at session initialization. `asyncio.wait_for` cannot interrupt it. The fix was to vendor the binary at a pinned version and launch it via direct exec (`MONGODB_MCP_COMMAND`). This took two days and a spike file to trace.

**HITL resume mechanics.** The ADK documentation suggests that a `LongRunningFunctionTool`'s function body re-runs on resume with the operator's response. It doesn't. The operator's `FunctionResponse` goes to the coordinator LLM, not back into the function. This means `request_human_approval` is a pure suspend gate; a separate `apply_approval_decisions` tool persists the per-item decisions; execution re-reads from MongoDB. Understanding this required reading the ADK source directly.

**The strategic agent reframe.** We almost built the wrong thing. The first design was a procedural pipeline: steps run in order, LLM at each node. It looked impressive on a diagram. But an agent that runs a fixed workflow in a fixed order is not reasoning — it is a workflow runner with a language model bolted on. Re-designing capability 5 into a genuine strategic decision happened mid-build, after the architecture was set. Propagating that change through the evaluation strategy, prompt design, operator UI, and documentation without breaking the nine capabilities that were already passing tests required careful sequencing.

**Calibration.** The exploitation path is grounded — the seed corpus, human-curated from real Wikimedia Commons sports photographs, governs routing. The exploration path is uncalibrated LLM judgment. We know it. The honest framing: the demo demonstrates the mechanism; a production system would require a human-scored reference set to validate the model's routing decisions against real operator outcomes.

---

## Accomplishments that we're proud of

The full nine-capability pipeline runs end-to-end — from a natural language batch submission through HITL approval to Shopify product creation — in under 60 seconds, with all 254 tests green.

MongoDB is load-bearing. Every capability touches Atlas — ingestion, vector search, scoring state, campaign queue, approval queue, social post queue, provenance records. Removing the MCP would not degrade the system; it would break it. That is the standard we held ourselves to, and we held it.

The data flywheel is real, not theoretical. The `record_outcomes` capability writes provenance records anchored at publish time, ready for a Shopify webhook to populate. The performance collection that grounds the next run's similarity search compounds with every event the system processes. That is MongoDB as persistent commercial memory, not just a runtime store.

Finally: we refused the easy framing. The temptation in a hackathon is to claim virality prediction, engagement optimization, or intent detection. We didn't. Exploitation candidates are grounded in vector similarity to past performers — "historically correlated signal," not a forecast. Exploration candidates are grounded in scored features: given each image's five Gemini Vision scores, any identifiable subjects, and the event narrative — with no similarity signal to lean on — the model decides whether the image merits surfacing, assigns it a commercial channel, and writes a one-sentence rationale the operator can read. Neither half claims to know what the internet will love. Both make claims that can be inspected, challenged, and improved.

---

## What we learned

The most durable lesson is about what kind of AI value is worth building.

There is **type-1 agentic value** — executing a workflow the human would have run anyway, just faster. And there is **type-2 agentic value** — making a judgment call in a small, bounded action space where reasonable people would disagree.

A pipeline runner is type-1. The strategic queue assembly decision is type-2. The entire project frame was about finding the one place where the agent earns its keep not by executing, but by deciding.

---

## What's next for Event Commerce Ops Agent

The immediate path is production calibration. The exploration queue is the system's most powerful capability; the right next step is building a human-scored reference set to measure how well the agent's routing decisions match what operators actually approve. That closes the loop between the strategic decision and real outcomes.

The data flywheel is ready to be activated. Right now, the `performance` collection records that outcomes are being tracked; a Shopify order webhook would populate the metrics in real time. Closing that loop means each subsequent event's similarity search is grounded in same-tournament performance data, not just historical priors — the system genuinely gets smarter across a tournament's run.

Beyond the MVP, the most natural expansions are multi-route assignment (an asset can simultaneously become a poster and a social post), multi-event-type support beyond soccer, and real social platform integration once the approval UI and post-scheduling workflow are proven on the simulated path.

The deeper opportunity, though, is not the sports commerce vertical. The architecture — historical similarity driving exploitation, agent judgment driving exploration, human approval before execution, persistent commercial memory that compounds — applies anywhere attention has a half-life and the bottleneck is the operational layer between capture and market. Concert photography. Breaking news. Product launches. Any domain where a moment is worth more right now than it will be tomorrow.

The World Cup is the demo. The problem is everywhere.
