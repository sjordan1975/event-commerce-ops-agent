# Project Close Hygiene

Tasks to complete before final demo/submission. Not on the critical path for capability development — address during wrap-up.

---

## 1. `pyproject.toml` dependency audit

**Status:** not done. All 9 capabilities are complete on `main` but the manifest has not been validated against actual imports.

### Current state

**Declared in `pyproject.toml`:**
```
google-adk==2.1.0
pydantic==2.13.4
python-dotenv==1.2.2

[dev]
pytest>=8.0
```

**What the code actually imports directly (non-stdlib):**

| Import | Package | In manifest? |
|--------|---------|-------------|
| `google.adk.*` | `google-adk` | ✅ explicit |
| `google.genai.*` | `google-genai` | ⚠️ transitive dep of `google-adk` |
| `mcp` (`src/db/client.py`) | `mcp` | ⚠️ transitive dep of `google-adk` |
| `anyio` (tests, `@pytest.mark.anyio`) | `anyio` | ⚠️ transitive dep of `google-adk` |

**Risk:** A clean `pip install -e ".[dev]"` probably works today because `google-adk` pulls in `google-genai`, `mcp`, and `anyio` as its own dependencies. If `google-adk` ever changes what it brings, those three disappear silently and imports break with no obvious cause.

### Steps to close

1. **Verify a clean install works** in a fresh venv:
   ```bash
   python3 -m venv /tmp/test-clean-install
   /tmp/test-clean-install/bin/pip install -e ".[dev]"
   /tmp/test-clean-install/bin/python -c "from src.agent import build_coordinator; print('ok')"
   /tmp/test-clean-install/bin/python -m pytest tests/ --ignore=tests/evals -q
   ```
2. **Promote direct deps** — `google-genai` and `mcp` are imported directly by `src/`; pin them explicitly alongside `google-adk`.
3. **Add `anyio` to dev deps** — tests use it directly via `@pytest.mark.anyio`.

---

## 2. `.env` config audit

All env vars read by `src/` — confirm each is documented in `.env.example` with its default and purpose:

**Required — pipeline will not start without these:**

| Variable | Default | Set in | Purpose |
|----------|---------|--------|---------|
| `GOOGLE_API_KEY` | _(required)_ | `src/capabilities/*.py` | Gemini API key for all LLM + embedding calls |
| `MONGODB_URI` | _(required)_ | `src/db/client.py` | Atlas connection string (passed to MCP server) |
| `MDB_MCP_API_CLIENT_ID` | _(required)_ | `src/db/client.py` | MongoDB Atlas MCP auth |
| `MDB_MCP_API_CLIENT_SECRET` | _(required)_ | `src/db/client.py` | MongoDB Atlas MCP auth |

**LLM model selection (all have usable defaults):**

| Variable | Default | Set in | Purpose |
|----------|---------|--------|---------|
| `GEMINI_COORDINATOR_MODEL` | `gemini-2.5-flash` | `src/agent.py` | Chat-mode coordinator (flash-lite unreliable at delegate-vs-dispatch) |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | `src/agent.py`, `src/capabilities/drafts.py` | Workflow nodes + copy drafting |
| `GEMINI_NARRATIVE_MODEL` | `gemini-2.5-flash-lite` | `src/capabilities/context.py` | Event narrative generation |
| `GEMINI_VISION_MODEL` | `gemini-2.5-flash` | `src/capabilities/scoring.py` | Vision scoring |
| `GEMINI_QUEUE_MODEL` | `gemini-2.5-flash` | `src/capabilities/queue.py` | Queue assembly strategic node |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | `src/capabilities/similarity.py` | Asset embeddings (3072-dim multimodal) |
| `GEMINI_IMAGE_MODEL` | `gemini-3-pro-image` | `src/capabilities/execution.py` | T-shirt mockup image generation |

**Pipeline tuning:**

| Variable | Default | Set in | Purpose |
|----------|---------|--------|---------|
| `PROMPT_VERSION` | `v3` | `src/prompt_loader.py` | Active prompt directory under `prompts/` |
| `VECTOR_INDEX_NAME` | `assets_embedding_index` | `src/db/assets.py` | Atlas vector search index name |
| `MAX_REDRAFT_CYCLES` | `3` | `src/agent.py` | Hard cap on HITL redraft loops |
| `QUEUE_MAX_PER_POOL` | `5` | `src/capabilities/__init__.py` | Functional reranker cap per pool (exploitation + discovery); max 10 total items in approval batch |
| `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` | `0.90` | `src/capabilities/__init__.py` | Similarity threshold for exploitation vs discovery split; calibrated empirically for demo corpus |

**Operational / optional:**

| Variable | Default | Set in | Purpose |
|----------|---------|--------|---------|
| `MONGODB_MCP_COMMAND` | vendored binary path | `src/api/server.py`, `src/db/client.py` | Path to MCP server binary; defaults to `src/api/node_modules/.bin/mongodb-mcp-server` (D-035 gotcha — do not use `npx`) |
| `MONGODB_MCP_VERSION` | `1.11.0` | `src/db/client.py` | MCP server version when launching via npx (only used if `MONGODB_MCP_COMMAND` not set) |
| `LOG_PIPELINE` | _(unset = off)_ | `src/api/server.py` | Set to `1` to enable verbose LLM call logging (start/done + latency) |
| `SHOPIFY_STORE_URL` | _(unset = preview mode)_ | `src/capabilities/execution.py` | Shopify dev store URL; without this, mockups stored locally |
| `SHOPIFY_CLIENT_ID` | _(unset = preview mode)_ | `src/capabilities/execution.py` | Shopify custom app client ID |
| `SHOPIFY_CLIENT_SECRET` | _(unset = preview mode)_ | `src/capabilities/execution.py` | Shopify custom app client secret |

Steps to close:
1. Rename `.env.template` → `.env.example` (convention; current name works but `.example` is standard)
2. Confirm required vars are clearly marked as non-optional in the example file
3. Verify `GOOGLE_APPLICATION_CREDENTIALS` is NOT needed — the codebase uses `GOOGLE_API_KEY` directly via `genai.Client(api_key=...)`, not ADC

---

## 3. Clone-and-run verification (the ultimate test)

The final check before submission: a clean clone must produce a passing test suite with no manual intervention beyond populating `.env`.

```bash
git clone <repo-url> fresh-clone
cd fresh-clone
cp .env.example .env   # fill in MDB_MCP_API_CLIENT_ID/SECRET + any GCP auth
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ --ignore=tests/evals -q   # all unit tests green
.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"
```

This subsumes items 1 and 2 above — if the clone-and-run passes, the dep audit and env audit are effectively verified together.

---

## 4. Other close items

- Review all `# TODO` / `# FIXME` comments left in code
- Remove or archive any spike files not needed for the demo
- Final review of hackathon rules (https://rapid-agent.devpost.com/rules) — e.g. submitted code must be open-source licensed (see "What to Submit:" section)
