# Demo Corpus Plan

**Status: active — Track 1 of delivery roadmap**
**Deadline: before demo recording (~Jun 9)**

This plan governs curation of the two demo event batches. The seeded historical corpus (64 assets, 4 events) is **fixed** — do not re-seed. Everything here is about the batches the operator "uploads" on camera.

---

## Order of work

**Images first. Narrative second.**

The kickoff messages — team names, match outcome, timestamp — are written *after* we know what images we actually have and have verified the similarity contrast. Locking in a narrative before curation means we end up finding images to fit a story rather than building the story from what we find.

```
1. Browse Wikimedia → find candidate images by visual genre
2. Probe similarity against live Atlas corpus
3. Assemble two batches that hit the target pool composition
4. Write the kickoff messages to match whatever the images actually depict
5. Commit the URL list in prep_demo_corpus.py
```

---

## The contrast that must land

`prepare_queue_candidates` splits at `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` (default `0.75`). Assets above go to exploitation; below to discovery. The LLM reasons over both pools every time — the contrast is in **pool composition**, not pool presence.

| Batch | Exploitation target | Discovery target | Visible difference on camera |
|-------|--------------------|-----------------|-----------------------------|
| Batch 1 — win outcome | 6–8 items | remainder | Agent orders a rich exploitation set, per-item proven reasoning |
| Batch 2 — draw outcome | 2–3 items | remainder | Agent works harder on discovery; different per-item justification |

This is the story. If these numbers don't land, the demo loses its through-line.

---

## Seed corpus summary (the fixed reference)

The seeded events and their `outcome_type` — what the similarity search runs against:

| Seed event | Outcome type | Image character |
|-----------|-------------|-----------------|
| `wc2022-final-arg-fra` | `extra_time_win` | Argentina celebrations, Messi/Mbappé portraits, team trophy shots |
| `wc2018-grp-kor-ger` | `upset_victory` | Korea vs Germany match action, Son portraits, celebration |
| `wc2014-final-ger-arg` | `expected_win` | Germany final action, Götze goal, German celebrations, Schweinsteiger |
| `wc2018-grp-esp-por` | `draw` | Spain/Portugal match action, Ronaldo/Iniesta/Piqué individual shots, pre-match lineup |

Embeddings encode visual + semantic content (`gemini-embedding-2` is multimodal). The similarity score reflects how much an image looks and reads like what's already in the corpus. **Visual genre drives the score, not event identity** — a celebration photo from any soccer match embeds near other celebration photos.

---

## Batch 1 image spec (win outcome — `/tmp/wc-final/`)

**Goal: majority of images land ≥ 0.75 similarity against the seeded corpus.**

### Why these will score high
The seeded corpus has three win-outcome events with celebration and portrait assets that scored well historically. New images in the same visual register embed close to those anchors.

### Target image types
- **Celebration shots**: players or teams visibly celebrating a win — same visual grammar as the `extra_time_win` / `upset_victory` seed assets
- **Star player portraits**: clean individual shots with strong identity signal — embed near the existing Messi, Mbappé, Son portrait cluster
- **Trophy / podium moments**: championship or post-match trophy lifts — visually distinctive, cluster together across events

### Avoid
- Pure action/play sequences (embed near match_action cluster — lower similarity)
- Wide stadium shots (too generic, low similarity)
- Anything that could fire the grounding guard (D-030): images where the agent can't confirm player identity

### Product route mix target
Aim for a mix that produces: ≥ 3 poster-routable (celebration, iconic moment), ≥ 2 tshirt-routable (clean portrait), remainder social_only. This makes the evidence section interesting — Shopify product cards in both poster and tshirt variants.

### Batch size
20–25 images. Enough for a 6–8 item exploitation queue with meaningful discovery remainder.

---

## Batch 2 image spec (draw outcome — `/tmp/wc-draw/`)

**Goal: most images land < 0.75; a few (2–3) land ≥ 0.75.**

### Why these will score low
Draw imagery is less commercially distinctive than win imagery. Match-action from a draw embeds near the lower-similarity action cluster, not near the celebration/portrait anchors that drive high exploitation scores.

### Target image types
- **Match action**: contested midfield duels, wide tactical shots, goalkeeper saves — less commercially distinctive
- **Team lineups / pre-match**: static but undramatic
- **Subdued bench/crowd reactions**: after a draw — not iconic
- **A few portraits** (2–3 max): individual player shots that will produce the small exploitation pool

### Avoid
- Celebration shots (would push exploitation count up — defeats the contrast)
- Trophy moments (same)
- Images visually identical to Batch 1 — the two events must look different on camera

### Product route mix target
Mostly social_only is correct for a draw. A small poster and tshirt minority is fine.

### Batch size
20–25 images.

---

## Hard constraints

1. **No demo images from the four seeded events — any photo, not just seeded URLs.** The forbidden events are:
   - `wc2022-final-arg-fra` (Argentina vs France, WC2022 Final)
   - `wc2018-grp-kor-ger` (South Korea vs Germany, WC2018 Group F)
   - `wc2014-final-ger-arg` (Germany vs Argentina, WC2014 Final)
   - `wc2018-grp-esp-por` (Spain vs Portugal, WC2018 Group B)

   This is stricter than the no-duplicate-URL rule below. Even a photo of these events that isn't in `SEED_IMAGES` is off-limits — the demo must represent a genuinely new event the agent has never seen. Using photos from seeded events would be circular: the system would appear to recognize events it already knows, not demonstrate commercial signal detection on new material.

2. **No URL duplicates from seed corpus.** `prep_demo_corpus.py` imports `SEED_IMAGES` from `scripts/seed_images.py` and asserts zero overlap before downloading anything. Failure mode: a seeded image in the demo batch gets ingested as a "new" event asset — its embedding is already in Atlas, producing an artificially perfect similarity match.

3. **CC-BY or CC-BY-SA license only.** Hackathon rules require open-source; judges may inspect. Wikimedia Commons is the source. Verify license on the file description page before adding a URL.

4. **Grounding guard safety (D-030).** The copy-drafting step names only `detected_subjects` it can verify — ambiguous crowd shots or identity-unclear action frames produce weak or empty copy. Prefer images where the focal subject is clearly identifiable.

5. **Local path reachability.** Images are served to the browser via the `/api/image?path=` proxy (already wired). No HTTPS hosting required.

---

## Operator kickoff messages

> **Finalize after curation.** The team names, match narrative, and outcome are filled in once we know what images we actually have. The structure below is fixed; the content slots are placeholders.
>
> **Each batch must be photos from a single real-world match.** The kickoff message tells the agent "here are tonight's photos" — if the batch mixes multiple matches, `build_event_context` builds an incoherent narrative. Choose one match per batch, then fill in the team names and outcome from that match.

> **Note on verbosity:** `build_event_context` *should* infer outcome_type from a terse message, but that path is untested on live data. We supply it explicitly — reliability on camera over naturalness.

**Batch 1 template:**
```
[Team A] vs [Team B].
[Team A] pulled off the upset over [Team B], [score].

Match started [ISO timestamp].
Outcome: upset_victory.

I uploaded the images to /tmp/wc-final directory.
Process the following images.
```

**Batch 2 template:**
```
[Team A] vs [Team B].
It finished [score] — both teams take the point.

Match started [ISO timestamp].
Outcome: draw.

I uploaded the images to /tmp/wc-draw directory.
Process the following images.
```

Fill in team names and score to match whatever events the curated images actually depict.

> **Team name precision (Batch 2):** `find_players_for_teams` matches the `team` field in player_context exactly against whatever home/away team strings the coordinator extracts and stores. Use the full formal name — "United States" not "USA", "Wales" not "Cymru" — so the player lookup resolves. The player_context entries use `team: "United States"` and `team: "Wales"` to match.

---

## `prep_demo_corpus.py` spec

The script must be **reproducible** — running it before any demo session restores both directories to the curated state.

### Structure
1. Import `SEED_IMAGES` from `scripts/seed_images.py`
2. Define `BATCH1_IMAGES` and `BATCH2_IMAGES` as lists of `{url, filename, tags, notes}` dicts
3. **Dedup assertion at startup**: extract all URLs from `SEED_IMAGES`, assert none appear in either batch — raise immediately if violated, listing the offending URLs
4. For each batch: `mkdir -p` the target dir, download each URL to `{dir}/{filename}`, skip if file already exists (idempotent)
5. Print summary: batch, path, file count, any download failures

### Filename convention
Short, descriptive filenames: `celebration_trophy_01.jpg`, `draw_midfield_action_02.jpg`. These appear in the agent's file listing — legible names help the coordinator's prompt context.

The `{url, filename}` pair in each dict **is the source-to-local map** — the script is the canonical record of where every file came from. To re-run or verify attribution, read the script; there is no separate mapping file needed.

### Download robustness
- **User-Agent**: import `WIKIMEDIA_HEADERS` from `scripts/seed_mongodb.py` — Wikimedia requires a descriptive User-Agent; reuse the existing constant rather than defining a second one
- **Inter-request delay**: 0.5–1s sleep between downloads — courteous for ~40 sequential requests and avoids triggering throttling
- **Retry on 429 / 5xx**: simple exponential backoff, 3 attempts, stdlib `time.sleep` — no external retry library needed
- **Idempotency is the primary safety net**: skip-if-exists means a failed mid-run is recoverable by re-running; retry handles transient failures within a single run

The 429 risk here is low (downloads only, no Gemini calls). Gemini 429s appear at pipeline run time during `find_similar_assets` embedding — that path has its own retry handling.

### No verification logic in the script
Pool composition verification is a separate step (run the agent, inspect similarity output). The script's only job is deterministic download.

---

## Verification gate (before committing the URL list)

Do this **after** downloading both batches, **before** writing the kickoff messages or finalizing the script:

1. Reset Atlas: `python scripts/reset_atlas.py`
2. Start the API: `.venv/bin/python3 -m uvicorn src.api.server:app --port 8000`
3. Send the Batch 1 kickoff message and let the pipeline run through `propose_review_queue`
4. Check the `capability_completed` SSE payload: `resultSummary` shows `N exploitation · M discovery candidates`
5. Repeat for Batch 2
6. **Gate**: Batch 1 must show 6–8 exploitation; Batch 2 must show 2–3. If not, swap images and re-run.

If the contrast isn't landing, the primary lever is **Batch 1 image type** — add more celebration/portrait images, remove action shots. The seed corpus is fixed.

---

## What's not in scope here

- Re-seeding the historical corpus (fixed, do not touch)
- `NEXT_PUBLIC_API_URL` env setup (already wired in `ui/.env`, gitignored)
- Cloud Run deploy (Track 4)
- Demo video pacing / screen recorder (Track 5)
