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

| Variable | Default | Set in | Purpose |
|----------|---------|--------|---------|
| `GEMINI_COORDINATOR_MODEL` | `gemini-2.5-flash` | `src/agent.py` | Chat-mode coordinator LLM (flash-lite unreliable at delegate-vs-dispatch) |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | `src/agent.py`, `src/capabilities/drafts.py` | Workflow nodes + copy drafting |
| `GEMINI_NARRATIVE_MODEL` | `gemini-2.5-flash-lite` | `src/capabilities/context.py` | Event narrative generation |
| `GEMINI_VISION_MODEL` | `gemini-2.5-flash` | `src/capabilities/scoring.py` | Vision scoring |
| `GEMINI_QUEUE_MODEL` | `gemini-2.5-flash` | `src/capabilities/queue.py` | Queue assembly strategic node |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | `src/capabilities/similarity.py` | Asset embeddings (3072-dim multimodal) |
| `MDB_MCP_API_CLIENT_ID` | _(required)_ | `src/db/client.py` | MongoDB Atlas MCP auth |
| `MDB_MCP_API_CLIENT_SECRET` | _(required)_ | `src/db/client.py` | MongoDB Atlas MCP auth |
| `VECTOR_INDEX_NAME` | `assets_embedding_index` | `src/db/assets.py` | Atlas vector search index name |
| `PROMPT_VERSION` | `v3` | `src/prompt_loader.py` | Active prompt directory under `prompts/` |
| `MAX_REDRAFT_CYCLES` | `3` | `src/agent.py` | Hard cap on HITL redraft loops |
| `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` | `0.75` | `src/capabilities/__init__.py` | Similarity threshold for exploitation pool |

Steps to close:
1. Verify `.env.example` exists and covers every row above
2. Confirm required vars (`MDB_MCP_API_CLIENT_ID`, `MDB_MCP_API_CLIENT_SECRET`) are clearly marked as non-optional
3. Check whether `GOOGLE_APPLICATION_CREDENTIALS` or equivalent Vertex AI auth env var needs documenting (used implicitly by `google-genai` SDK)

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
