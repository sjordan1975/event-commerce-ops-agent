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

The agent is not a content creator. It is a **commercial operations coordinator**.

The system does not ask: *"What image is prettiest?"*

It asks: *"What asset is most likely to produce downstream economic action — and what is the fastest path to getting it in front of a buyer?"*

This distinction is load-bearing. It determines every scoring decision, every routing decision, and every MCP call the agent makes.

---

## The Demo Narrative

> "A chaotic post-match media workflow became operationally organized by an AI agent."

The demo should feel operational, not analytical. Judges should see:

1. A batch of event photos arrives
2. The agent reasons about commercial potential, not aesthetics
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
| "AI picks your best photos" | "AI coordinates monetization workflows from live event media" |
| "AI marketing optimization platform" | "Operational prioritization under time pressure" |
| "Predicts virality" | "Operationalizes historically correlated signals to prioritize high-potential commercial assets" |

The last row is the language to use with judges. Never claim virality prediction. It's pseudoscientific and unvalidatable in a hackathon demo.

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
- Operates on **commercial conversion logic**, not aesthetics
- Executes **real-world workflows via MCP** at every step
- Coordinates **multi-system actions** (MongoDB, Shopify, Printful) as a single orchestrated pipeline
- Optimizes for **operational speed**, not content quality scores
- Grounds scoring decisions in **historical performance data** via vector search — not pure LLM inference

---

## Key Risks

- **Scope creep:** Supporting multiple event types, social platforms, or ecommerce systems will collapse the timeline. MVP scope is hard-limited — see `01-requirements.md`.
- **Engagement prediction trap:** Claiming to predict virality weakens credibility. Frame all scoring as "historically correlated signal" language.
- **MCP decorativeness:** If MongoDB could be removed without breaking the demo, the partner integration fails the judging test. Every MongoDB call must be load-bearing.
- **Demo complexity:** If the demo requires explaining the architecture, the demo has failed. The workflow should be self-evident.
