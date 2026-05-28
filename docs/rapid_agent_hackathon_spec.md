# Hackathon Spec: Google Cloud Rapid Agent Hackathon
**Source:** https://rapid-agent.devpost.com/  
**Deadline:** June 11, 2026 @ 2:00 PM PDT  
**Prize Pool:** $60,000 in cash  
**Participants:** ~9,100+ registered

---

## Core Directive

> "AI that doesn't just provide answers—it helps you take action."

The hackathon is explicitly about **agents that accomplish tasks**, not chatbots that answer questions. Built on **Gemini** (the reasoning brain) + **Google Cloud Agent Builder** (the build environment) + **one partner's MCP server** (the "superpowers").

---

## The Three Non-Negotiable Requirements

### 1. Move Beyond Chat
The agent must use tools and capabilities to **accomplish tasks**. Examples from the spec: managing a local database, automating a hobbyist workflow, interacting with a live web service. Answering questions is not sufficient.

### 2. The Multi-Step Mission
The agent must handle **complex, multi-step goals**. It should plan steps, select tools, and execute — while keeping the human in control. Single-turn completions will not score well.

### 3. Partner Power
The submission **must** demonstrate a meaningful integration with at least one partner's MCP server. This is not optional. The MCP integration is the mechanism by which the agent gets its domain-specific superpowers.

---

## Suggested Problem Domains

The spec offers three example themes (non-exclusive, any real-world problem is valid):

- **2026 World Cup** — Fan logistics automation, tourist surge management for local businesses, fully automated fantasy league.
- **Financial Services** — Real-time fraud detection, loan workflow automation, personalized wealth management execution.
- **Brick-and-Mortar Retail** — Real-time shopper navigation, hyper-local tenant campaigns, facility operations automation.

The spec also explicitly invites: work, personal life, hobbies, and daily routines. Personal scope is valid.

---

## Required Build Stack

| Component | Role | Notes |
|-----------|------|-------|
| **Gemini** (any version via Agent Platform) | Reasoning / LLM brain | Required |
| **Google Cloud Agent Builder** | Primary build + orchestration environment | Recommended for rapid prototyping; required unless using code-only path |
| **Partner MCP Server** (one of 6) | Domain superpowers / tool integration | Required — must be meaningful, not cosmetic |
| **Agent Runtime** (optional) | Deploy Python-based agents (LangChain, LlamaIndex) | Use for custom orchestration logic |
| **Cloud Run** (optional) | Host custom agent backends or tool servers | Use if deploying outside Agent Builder |

**Google Cloud access:** Free trial at cloud.google.com/free, or request $100 in credits via https://forms.gle/xfv9vQzfRfNCCVbG7 (approved in 1–5 business days).

---

## Build Path Overview (5 Phases from Resources Page)

**Phase 1 — Core Frameworks & Environment**
- Managed path: Google Cloud Agent Builder (low-code, managed orchestration)
- Code path: Gemini Enterprise Agent Platform SDK for Python
- Starter kit: https://github.com/GoogleCloudPlatform/agent-starter-pack

**Phase 2 — Action Mechanisms & Data Connectivity**
- Tool use via Agent Builder Extensions (pre-built Google extensions or external APIs)
- Grounding via Agent Builder Data Stores (index PDFs, websites, BigQuery tables)

**Phase 3 — Partner Integration**
- Choose one of the 6 partners; integrate their MCP server (see partner details below)

**Phase 4 — Reasoning, State & Logic**
- Agent Runtime for deploying Python-based agents
- Secret Manager for API keys

**Phase 5 — Deployment & Safety**
- Agent Builder deployment for managed agents
- Cloud Run for custom backends
- Gemini Safety Settings for guardrails

---

## Prize Structure

Six partner tracks, each with identical prize buckets. Submissions compete **within their chosen partner track only**.

| Place | Prize |
|-------|-------|
| 1st | $5,000 |
| 2nd | $3,000 |
| 3rd | $2,000 |

Six tracks × $10,000 per track = **$60,000 total**.

---

## Judging Criteria

Judges are drawn from each partner organization plus Google Cloud engineers.

1. **Technological Implementation** — Quality of integration with Google Cloud and partner services.
2. **Design** — UX and overall design quality.
3. **Potential Impact** — Scale of impact on target communities.
4. **Quality of the Idea** — Creativity and uniqueness.

---

## Submission Requirements

- URL to the **hosted project**
- URL to **public open-source code repository** (must include a detectable OSS license at the top of the repo)
- **~3 minute demo video**
- **Partner track selection** (which of the 6 partners)
- Completed Devpost submission form

---

## Partner Tracks

You must pick exactly one. Each partner provides an MCP server to integrate. Full details below.

---

### Partner 1: Arize

**What they are:** AI engineering platform for evaluation and observability of AI agents and applications. The product is called Arize Phoenix. Focus: tracing, evals, datasets, experiments, and prompts — in development and in production.

**What the MCP server does:** The Phoenix MCP server (`@arizeai/phoenix-mcp`, runs via `npx`) lets your agent **query its own traces, prompts, datasets, and experiments at runtime**. This enables agents that can inspect their own behavior and self-improve.

**Track-specific requirements:**
- Requires a **code-owned agent runtime**: Gemini CLI, Gemini Enterprise Agent Platform SDK, Google ADK, Agent Runtime, or Cloud Run. Visual Agent Builder alone is not supported (you need to instrument code directly).
- Must instrument with **OpenInference** (OpenTelemetry-compatible; auto-instrumentors available for Google ADK, Vertex AI, LangChain, LlamaIndex, etc.)
- Must send traces to Phoenix Cloud (free SaaS) or self-hosted Phoenix
- Must configure the Phoenix MCP server so the agent can introspect its own operational data at runtime
- Must run evaluations (LLM-as-Judge or code evals)
- Bonus: agents that use their own observability data to improve over time

**Judging emphasis:** Technical implementation, meaningful use of tracing + MCP, quality of the agent's self-improvement loop, overall impact.

**Key resources:**
- Phoenix Cloud (free): https://app.phoenix.arize.com
- Phoenix GitHub (open-source, self-hostable): https://github.com/Arize-ai/phoenix
- Phoenix docs: https://arize.com/docs/phoenix
- Phoenix MCP Server guide: https://arize.com/docs/phoenix/integrations/phoenix-mcp-server
- OpenInference GitHub: https://github.com/Arize-ai/openinference
- Hackathon quickstart repo: https://github.com/Arize-ai/gemini-hackathon
- Contact: ryoung@arize.com

**Instrumentors:**
- Google ADK: `openinference-instrumentation-google-adk`
- Vertex AI / Gemini Enterprise Agent Platform SDK: `openinference-instrumentation-vertexai`
- google-genai SDK: `openinference-instrumentation-google-genai`

---

### Partner 2: Elastic

**What they are:** The "Search AI Company." Elastic integrates search technology with AI to transform data into answers, actions, and outcomes. Their Search AI Platform underpins search, observability, and security products. Used by more than 50% of the Fortune 500.

**What the MCP server does:** Gives agents powerful full-text search, vector search, and hybrid search over indexed data — enabling high-quality semantic retrieval as a live tool call.

**Key use cases for agents:** Semantic search over large corpora, log analysis, security event correlation, knowledge base retrieval.

**Resources:** The partner page notes "Coming soon" for detailed technical resources. Monitor https://rapid-agent.devpost.com/details/elastic-resources for updates.

---

### Partner 3: Fivetran

**What they are:** Automated data movement platform — moves, manages, and transforms data from every business system into a reliable, secure foundation. Used by LVMH, Pfizer, Verizon, and OpenAI. Self-described as "the data foundation for AI."

**What the MCP server does:** Gives agents control over Fivetran connectors, pipelines, and data syncs — enabling agents that can trigger, monitor, or manage ETL workflows as part of multi-step tasks.

**Integration options (choose one):**
- **Option 1 (MCP):** Fork and run the open-source Fivetran MCP server: https://github.com/fivetran/fivetran-mcp
- **Option 2 (REST API):** Use Fivetran REST APIs directly: https://fivetran.com/docs/rest-api — example project at https://github.com/fivetran/api_framework

**Getting started:**
- Free 14-day trial (no access code): https://fivetran.com/signup
- API key for both MCP and REST: https://fivetran.com/docs/rest-api/getting-started#authentication
- BigQuery destination quickstart: https://fivetran.com/docs/destinations/bigquery/setup-guide

**Key use cases for agents:** Agents that manage data pipelines, trigger syncs on events, validate data freshness before analysis, automate data onboarding workflows.

---

### Partner 4: GitLab

**What they are:** A complete DevSecOps platform delivered as a single application. Covers the full software development lifecycle: plan, code, build, test, secure, deploy, monitor. From idea to production.

**What the MCP server does:** Exposes GitLab repositories, issues, pipelines, merge requests, and the Duo Agent Platform to the agent — enabling agents that can reason about code, open issues, trigger pipelines, and interact with the full DevSecOps workflow.

**Access:** 30-day Ultimate trial — no access code required. Includes Duo Agent Platform with 24 credits per user, custom agents (GA), custom flows (Beta), AI Catalog (GA), and the MCP server (Beta). Start at: https://about.gitlab.com/free-trial/

**Important note:** Participants using external tools to call GitLab via MCP must set a default Duo namespace. In-GitLab usage works without this.

**Key resources:**
- Get started: https://docs.gitlab.com/user/get_started/get_started_agent_platform/
- Custom agents: https://docs.gitlab.com/user/duo_agent_platform/agents/custom/
- Custom flows (Beta): https://docs.gitlab.com/user/duo_agent_platform/flows/custom/
- AI Catalog: https://docs.gitlab.com/user/duo_agent_platform/ai_catalog/
- MCP Server (Beta): https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/

**Upcoming event:** "Secure AI Agent Deployment with GitLab and Gemini" — Discord build session, May 26 @ 1:00 PM EDT / 10:00 AM PDT.

**Key use cases for agents:** Automated code review agents, issue triage agents, CI/CD trigger agents, security scanning automation, DevOps workflow orchestration.

---

### Partner 5: MongoDB

**What they are:** MongoDB Atlas is described as a "unified operational foundation and persistent memory layer for modern AI and agentic workloads." Combines operational data, vector search, and semantic data on one platform. Framework-agnostic.

**What the MCP server does:** Connects the agent directly to a MongoDB database — enabling natural-language database queries, document management, aggregation pipelines, and vector search as live tool calls.

**Key resources:**
- MongoDB MCP Server docs: https://www.mongodb.com/docs/mcp-server/get-started/
- Sample Mflix dataset (already includes vector embeddings for Vector Search): https://www.mongodb.com/docs/atlas/sample-data/sample-mflix
- Atlas Vector Search: https://www.mongodb.com/products/platform/atlas-vector-search
- Atlas Search: https://www.mongodb.com/docs/atlas/atlas-search/
- Aggregation Pipelines: https://www.mongodb.com/docs/manual/aggregation/
- Data Modelling guide: https://www.mongodb.com/docs/manual/data-modeling/
- Voyage AI (embedding generation): https://www.mongodb.com/products/platform/ai-search-and-retrieval
- AI Learning Hub: https://www.mongodb.com/resources/use-cases/artificial-intelligence
- MongoDB Tools: https://www.mongodb.com/try/download/database-tools

**Key use cases for agents:** Agents with persistent memory across sessions, semantic search over domain data, multi-modal data retrieval, recommendation agents, agents that read/write structured records as part of workflows.

---

### Partner 6: Dynatrace

**What they are:** Application observability and performance monitoring platform. Helps developers and AI engineers understand how applications behave from code to production. Connects what you write to how services, data pipelines, and agents actually run.

**What the MCP server / integration does:** Instruments agents with OpenTelemetry to ship traces, metrics, and logs to Dynatrace — enabling agents to track token spend, tool calls, latency, and errors across Vertex AI, Gemini, and coding agents. Runtime context flows into the development workflow for validation, debugging, and scaling.

**Key resources:**
- Sign up (free trial): https://www.dynatrace.com/signup/
- Dynatrace for Agent Platform (Vertex AI): https://www.dynatrace.com/hub/detail/vertex-ai/
- Dynatrace for Gemini Enterprise (one-click from GCP Marketplace): https://console.cloud.google.com/marketplace/product/dynatrace-marketplace-prod/dynatrace-for-gemini-enterprise
- AI Coding Agent Monitoring (Claude Code, Gemini CLI, Codex CLI, OpenCode, GitHub Copilot SDK): https://www.dynatrace.com/news/blog/dynatrace-expands-ai-coding-agent-monitoring/
- Instrumentation examples on GitHub: https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples/tree/main/ai-coding-agents
- Bindplane (OTel telemetry pipeline, free for Google Cloud customers): https://bindplane.com/google

**Key use cases for agents:** Production-grade observability for any agent, cost tracking (token spend), debugging multi-step agent behavior, validating model behavior across deployments, agents that monitor other systems' health.

---

## Partner Selection Decision Guide

| If you want to build an agent that… | Choose |
|-------------------------------------|--------|
| Can observe and improve itself using its own trace data | **Arize** |
| Performs high-quality semantic / full-text search over large data | **Elastic** |
| Manages or triggers data pipelines and ETL workflows | **Fivetran** |
| Interacts with code repos, CI/CD, issues, merge requests | **GitLab** |
| Reads/writes to a database, uses vector search, maintains memory | **MongoDB** |
| Monitors application health, tracks telemetry, traces model behavior in prod | **Dynatrace** |

---

## What Will Likely Score Well

Based on the judging criteria and stated guidance:

1. A clear real-world problem that the agent *actually solves* (not just demonstrates)
2. True multi-step autonomy — the agent plans, selects tools, and executes across multiple turns
3. The MCP integration is load-bearing, not decorative (partner capability is central to the agent's function)
4. A working hosted demo (not just a video of local execution)
5. Clean, public, licensed code repository

## What Will Likely Score Poorly

- An agent that primarily answers questions (chatbot pattern)
- MCP integration that exists but doesn't affect the agent's core capability
- Single-turn or trivially short task chains
- Visual Agent Builder only (especially for the Arize track, which explicitly disallows it)
- Missing hosted project URL or private repository
