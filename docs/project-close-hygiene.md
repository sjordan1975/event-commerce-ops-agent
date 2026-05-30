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

## 2. Other close items (placeholder)

- Review all `# TODO` / `# FIXME` comments left in code
- Confirm `.env.example` covers every env var the agent reads
- Remove or archive any spike files not needed for the demo
