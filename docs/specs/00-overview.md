# 00 — Overview: Vision, Origin, and Positioning

## Origin

This project is a submission for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) (deadline: June 11, 2026, $60,000 prize pool, ~9,100 registered participants). The hackathon requires agents that *accomplish tasks* — not chatbots that answer questions — built on Gemini + Google Cloud Agent Builder (or SDK) + one partner MCP server as a load-bearing capability.

We are competing in the **MongoDB partner track**.

---

## The Problem

Live events generate massive volumes of media. A World Cup match ends and thousands of photos land in a queue. The commercial window is already decaying.

The problem is not finding the "best" photo. That's a commoditized aesthetic ranking problem.

The real problem is **operational speed under time pressure**:

- Manual triage is too slow to capitalize on engagement spikes
- Monetization windows for sports moments close within hours
- Distribution across merch, ecommerce, and social is fragmented
- Humans are the bottleneck

This is an **attention half-life** problem. Sports moments decay commercially very quickly. An agent that can move faster than a human team — triaging, packaging, routing, and queuing — has real economic value.

---

## The Solution Framing

The agent is not a content creator. It is a **commercial logistics coordinator**.

The system does not ask: *"What image is prettiest?"*

It asks: *"Which assets look like past winners for each channel — and what is the fastest path to getting them in front of a buyer?"*

The answer comes from per-channel image similarity against past performers, not novel AI reasoning. Find assets that look like past poster winners and route them to Shopify. Find assets that look like past social winners and queue them for posting. Get both to market before the attention window closes.

This framing is load-bearing. It determines every routing decision and every MCP call the agent makes. The value is operational speed and execution pipeline — not the sophistication of the scoring.

---

## The Demo Narrative

> "A chaotic post-match media workflow became operationally organized by an AI agent."

The demo should feel operational, not analytical. Judges should see:

1. A batch of event photos arrives
2. The agent finds assets similar to past channel winners and assigns routing — poster, t-shirt, or social
3. Workflows are created, queued, and routed
4. A human approves
5. The world changes — products exist, posts are queued, fulfillment is staged

**What to avoid in the demo:**
- Long explanations or narration
- Dashboards and analytics overload
- "Here's our architecture" slides
- Vague engagement predictions
- AI talking about itself

**What to show:**
- Ingestion → triage → orchestration → execution. Fast. Operational.

---

## Why This Demo Works for the Hackathon

1. **Multi-step planning** — not a single prompt-response
2. **Operational orchestration** — coordinates workflows across systems
3. **Meaningful MCP usage** — MongoDB is runtime infrastructure, called at every step
4. **Human-in-the-loop governance** — approval gate before execution; builds credibility
5. **Real economic objective** — commercial conversion, not engagement vanity metrics
6. **Visible execution** — products, posts, and listings are actually created (or credibly simulated)

---

## Scoring Philosophy: Optimization Surfaces, Not a Single "Best"

The agent does not pick one "best image." It scores assets across five dimensions:

Five dimensions are scored per image by Gemini Vision:

| Score | What it measures |
|-------|-----------------|
| `quality_score` | Technical fitness — sharpness, exposure, resolution, printability |
| `emotional_score` | Intrinsic moment intensity — peak human drama visible in the frame |
| `social_score` | Scroll-stopping probability — visual impact at thumbnail scale without context |
| `merch_score` | Suitability for physical products: silhouette clarity, graphic potential, poster framing |
| `identity_score` | Fan belonging signal — team colors, player number/face clearly recognizable |

`timeliness` is an event-level field, not scored per image. It is computed once at ingestion from `outcome_type` and hours since kickoff, and read from the `events` document during routing.

An asset may score high on `social_score` and low on `merch_score`. Routing follows the score profile, not a single ranking.

An iconic goal celebration in sharp focus beats a technically perfect midfield shot — because it scores high on `emotional_score`, `identity_score`, and the event's `timeliness`.

---

## Positioning

| Wrong framing | Right framing |
|--------------|---------------|
| "AI for creators" | "Real-time event commerce operations agent" |
| "AI picks your best photos" | "AI routes assets similar to past channel winners to market at operational speed" |
| "AI marketing optimization platform" | "Operational logistics under time pressure" |
| "Predicts virality" | "Image similarity to past performers, deployed before the attention window closes" |
| "Detects commercial intent" | "Finds what worked before and gets it to market faster than a human team" |

Never claim virality prediction or intent detection. The honest claim is logistics and speed: similarity search surfaces the candidates, the pipeline executes the deployment.

---

## Target Users

- Sports media teams (post-match workflow)
- Event photographers managing commercial rights
- Creator-commerce operators running merch drops
- Merchandising startups operating on event cycles
- Live event content teams with tight deployment windows

---

## Differentiation

Unlike traditional AI media tools, this system:

- Routes on **per-channel similarity to past performers**, not aesthetic ranking
- Executes **real-world workflows via MCP** at every step
- Coordinates **multi-system actions** (MongoDB, Shopify, Printful) as a single orchestrated pipeline
- Optimizes for **operational speed**, not content quality scores
- Uses **image similarity to channel-specific past winners** as the scoring engine — not LLM inference about what might work

---

## Real-World Deployment Story

### The cold-start answer

A common question: *where does the historical data come from on day one?*

A real customer — a World Cup media team, a sports rights holder, a creator-commerce operator — already has it. Every past tournament produced thousands of images that were commercially deployed. They know which assets became posters, which social posts drove merch sales, which photos underperformed. That data lives in their existing digital asset management system and sales analytics.

Onboarding looks like this:
1. Ingest historical images → generate embeddings via `gemini-embedding-2`
2. Pull past sales and engagement records → load into the `performance` collection
3. That corpus becomes the grounding layer the agent reasons from on day one of the next event

The seed data is not a workaround. It is the onboarding story.

### The data flywheel

The system compounds across events:

- **Match 1:** Agent reasons from historical archive (WC2022, WC2018, etc.)
- **Match 1 completes:** Outcomes — what sold, what converted, what was skipped — feed back into `performance`
- **Match 2:** Vector search is better-grounded than Match 1, now informed by same-tournament patterns
- **Knockout rounds:** Agent is reasoning from tournament-specific signals, not just historical priors

MongoDB is not just a runtime store. It is the persistent commercial memory that compounds in value across every event the system processes. This is why the MCP integration is load-bearing: remove it and the system loses its ability to learn.

### The demo framing

The hackathon demo uses 40 real licensed sports images (Wikimedia Commons) with synthetic but plausible conversion data. This is a compressed version of what a real customer would bring at onboarding.

The honest framing for judges: *"A real customer would connect their archive. We seeded with historical-style data to show the system operating as it would on day two of a real deployment — not day one, when the corpus is empty, and not day one hundred, when the patterns are fully established."*

This framing is more credible than claiming cold-start perfection. It also sets up the flywheel story naturally: the value of the system grows with every event it processes.

### Who buys this

- **Sports media teams** — post-match workflow automation; compress the commercial window from hours to minutes
- **Event photographers** managing commercial rights — triage and route at scale without a dedicated ops team
- **Creator-commerce operators** running merch drops — systematic prioritization instead of gut-feel selection
- **Merchandising startups** on event cycles — compete with larger teams by automating the operational layer

The common thread: they all face the same attention half-life problem, and they are all currently losing commercial value to manual process speed.

---

## Key Risks

- **Scope creep:** Supporting multiple event types, social platforms, or ecommerce systems will collapse the timeline. MVP scope is hard-limited — see `01-requirements.md`.
- **Engagement prediction trap:** Claiming to predict virality weakens credibility. Frame all scoring as "historically correlated signal" language.
- **MCP decorativeness:** If MongoDB could be removed without breaking the demo, the partner integration fails the judging test. Every MongoDB call must be load-bearing.
- **Demo complexity:** If the demo requires explaining the architecture, the demo has failed. The workflow should be self-evident.
- **Exploration vs. exploitation gap:** Pure similarity ranking removes novel content from human consideration before the queue is populated — the HITL gate is downstream of the filter and cannot correct for it. **Addressed in MVP via a 10% random discovery queue:** randomly sampled candidates bypass the similarity filter and reach the human regardless of score. Random is the maximally honest exploration strategy; it cannot structurally exclude anything. The exploration rate and sampling method (random, low-similarity tail, diversity-constrained) are deliberately left as customer and implementation decisions — different operators want different discovery behavior. See `01-requirements.md` for the full tuning space.
