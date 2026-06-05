"""Download demo event batch images into the project data directory.

Two batches:
  Batch 1 — win/upset outcome  →  data/wc-final/
  Batch 2 — draw outcome       →  data/wc-draw/

Usage (from project root):
    python scripts/prep_demo_corpus.py
    python scripts/prep_demo_corpus.py --dry-run

No API keys required — downloads only, no embedding calls.
Populate BATCH1_IMAGES and BATCH2_IMAGES before running (see docs/plans/demo-corpus.md).
"""

import argparse
import sys
import time
from pathlib import Path

import requests

from seed_images import SEED_IMAGES

# Mirrors seed_mongodb.WIKIMEDIA_HEADERS — keep in sync if User-Agent changes there.
_WIKIMEDIA_HEADERS = {
    "User-Agent": "realtime-event-commerce-ops-agent/0.1 (https://github.com/example/repo; demo-corpus)"
}

# ---------------------------------------------------------------------------
# Batch definitions
# ---------------------------------------------------------------------------
#
# Each entry must have:
#   url      — Wikimedia Commons full image URL (CC-BY or CC-BY-SA only)
#   filename — local filename saved under the batch directory
#   tags     — visual genre tags for reference (["celebration"], ["portrait"], etc.)
#   notes    — license / attribution note (for record-keeping)
#
# Constraints (see docs/plans/demo-corpus.md):
#   - Photos must NOT be from the four seeded events:
#       wc2022-final-arg-fra, wc2018-grp-kor-ger,
#       wc2014-final-ger-arg, wc2018-grp-esp-por
#   - No URL overlap with SEED_IMAGES (asserted at startup)
#   - All images in a batch must be from a single real-world match
#   - Fill in the kickoff message template (docs/plans/demo-corpus.md)
#     AFTER curation and similarity verification

BATCH1_IMAGES: list[dict] = [
    # Source: 2018 FIFA World Cup Final — France vs Croatia, 4-2 France win, Luzhniki Stadium.
    # Outcome type for kickoff: expected_win
    # Visual genre: trophy celebrations + player portraits → embeds near seeded celebration/portrait cluster.
    # NOT from any seeded event (seeded events: wc2022-final-arg-fra, wc2018-grp-kor-ger,
    #   wc2014-final-ger-arg, wc2018-grp-esp-por).
    # Excluded seeded URLs from this match: Kylian_Mbappé_2018.jpg, Kylian_Mbappé_France.jpg,
    #   Croatia's_post-match_huddle_after_the_2018_FIFA_World_Cup_Final.jpg

    # --- Trophy / celebration (6) ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/29/Antoine_Griezmann_World_Cup_Trophy.jpg",
        "filename": "france_griezmann_trophy.jpg",
        "tags": ["celebration", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/61/Kylian_Mbapp%C3%A9_World_Cup_Trophy.jpg",
        "filename": "france_mbappe_trophy.jpg",
        "tags": ["celebration", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/2c/Blaise_Matuidi_World_Cup_Trophy.jpg",
        "filename": "france_matuidi_trophy.jpg",
        "tags": ["celebration", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/17/Adil_Rami_World_Cup_Trophy.jpg",
        "filename": "france_rami_trophy.jpg",
        "tags": ["celebration", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/86/Benjamin_Mendy_World_Cup_Trophy.jpg",
        "filename": "france_mendy_trophy.jpg",
        "tags": ["celebration", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/78/Corentin_Tolisso_World_Cup_Trophy.jpg",
        "filename": "france_tolisso_trophy.jpg",
        "tags": ["celebration", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },

    # --- Team celebration (2) ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/14/France_celebrate_on_the_field_of_Luzhniki_after_the_2018_FIFA_World_Cup_Final.jpg",
        "filename": "france_team_celebrate_field.jpg",
        "tags": ["celebration", "team_shot"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e5/France_champion_of_the_Football_World_Cup_Russia_2018.jpg",
        "filename": "france_team_champion.jpg",
        "tags": ["celebration", "team_shot"],
        "notes": "CC-BY-SA 3.0",
    },

    # --- Awards / ceremony (1) ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e2/Luka_Modri%C4%87_receives_the_golden_ball_prize_at_the_hands_of_Russian_President_Vladimir_Putin.jpg",
        "filename": "modric_golden_ball_award.jpg",
        "tags": ["award_ceremony", "portrait"],
        "notes": "CC-BY-SA 3.0",
    },

    # --- Player portraits (3) ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/4/49/Antoine_Griezmann_in_2018.jpg",
        "filename": "griezmann_portrait_2018.jpg",
        "tags": ["portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/fc/Antoine_Griezmann_in_2018_%28cropped%29.jpg",
        "filename": "griezmann_portrait_2018_crop.jpg",
        "tags": ["portrait"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/ee/Ante_Rebi%C4%87_2018.jpg",
        "filename": "rebic_portrait_2018.jpg",
        "tags": ["portrait"],
        "notes": "CC-BY-SA 3.0",
    },

    # --- Match action (7) ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/8b/2018_World_Cup_Final_%282018-07-15%29_01.jpg",
        "filename": "final_2018_action_01.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/0/0a/2018_World_Cup_Final_%282018-07-15%29_02.jpg",
        "filename": "final_2018_action_02.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/1a/2018_World_Cup_Final_%282018-07-15%29_03.jpg",
        "filename": "final_2018_action_03.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/10/2018_World_Cup_Final_%282018-07-15%29_04.jpg",
        "filename": "final_2018_action_04.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/bd/2018_World_Cup_Final_-_France_v_Croatia_-_1st_Half.jpg",
        "filename": "final_2018_first_half.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/3/36/2018_World_Cup_Final_-_France_v_Croatia.jpg",
        "filename": "final_2018_action_wide.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e6/Final_of_the_Soccer_World_Cup_Russia_between_the_national_teams_of_France_and_Croatia.jpg",
        "filename": "final_2018_overview.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 3.0",
    },
]

BATCH2_IMAGES: list[dict] = [
    # Source: 2022 FIFA World Cup Group B — USA vs Wales, 1-1 draw, Ahmad bin Ali Stadium.
    # Outcome type for kickoff: draw
    # Visual genre: match action (majority) + a few player portraits for small exploitation pool.
    # NOT from any seeded event.

    # --- Match action (17) — numbered series, CC-BY-SA 4.0 ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/7b/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%281%29.jpg",
        "filename": "usa_wales_action_01.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/21/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%282%29.jpg",
        "filename": "usa_wales_action_02.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/aa/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%283%29.jpg",
        "filename": "usa_wales_action_03.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/0/09/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%284%29.jpg",
        "filename": "usa_wales_action_04.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/9/9b/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%285%29.jpg",
        "filename": "usa_wales_action_05.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/be/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%286%29.jpg",
        "filename": "usa_wales_action_06.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/b9/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%287%29.jpg",
        "filename": "usa_wales_action_07.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/1b/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%288%29.jpg",
        "filename": "usa_wales_action_08.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/b0/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%289%29.jpg",
        "filename": "usa_wales_action_09.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/11/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2810%29.jpg",
        "filename": "usa_wales_action_10.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/83/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2811%29.jpg",
        "filename": "usa_wales_action_11.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/9/9d/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2813%29.jpg",
        "filename": "usa_wales_action_13.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2814%29.jpg",
        "filename": "usa_wales_action_14.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/bb/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2815%29.jpg",
        "filename": "usa_wales_action_15.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/82/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2816%29.jpg",
        "filename": "usa_wales_action_16.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/3/3d/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2817%29.jpg",
        "filename": "usa_wales_action_17.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/16/2022_FIFA_World_Cup_United_States_1%E2%80%931_Wales_-_%2818%29.jpg",
        "filename": "usa_wales_action_18.jpg",
        "tags": ["match_action"],
        "notes": "CC-BY-SA 4.0",
    },

    # --- Player portraits (3) — for small exploitation pool ---
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/77/Matt_Turner_2022.jpg",
        "filename": "matt_turner_portrait.jpg",
        "tags": ["portrait"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/81/Tyler_Adams_WC2022.jpg",
        "filename": "tyler_adams_portrait.jpg",
        "tags": ["portrait"],
        "notes": "CC-BY-SA 4.0",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/10/Brennan_Johnson_WC2022.jpg",
        "filename": "brennan_johnson_portrait.jpg",
        "tags": ["portrait"],
        "notes": "CC-BY-SA 4.0",
    },
]

_HERE = Path(__file__).parent.parent  # project root
_BATCHES = [
    {"name": "Batch 1 (win/upset)", "dir": _HERE / "data" / "wc-final", "images": BATCH1_IMAGES},
    {"name": "Batch 2 (draw)",      "dir": _HERE / "data" / "wc-draw",  "images": BATCH2_IMAGES},
]

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _assert_no_seed_overlap() -> None:
    seed_urls = {img["url"] for img in SEED_IMAGES}
    violations = [
        (img["filename"], img["url"])
        for batch in _BATCHES
        for img in batch["images"]
        if img["url"] in seed_urls
    ]
    if violations:
        lines = "\n".join(f"  {fname}: {url}" for fname, url in violations)
        raise SystemExit(f"ERROR: demo batch URLs overlap with SEED_IMAGES:\n{lines}")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_with_retry(url: str, dest: Path, max_attempts: int = 3) -> None:
    """Fetch url → dest, retrying on 429 / 5xx with exponential backoff."""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, headers=_WIKIMEDIA_HEADERS, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < max_attempts:
                    wait = 2 ** attempt
                    print(f"    HTTP {resp.status_code} — retrying in {wait}s (attempt {attempt}/{max_attempts})")
                    time.sleep(wait)
                    continue
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return
        except requests.RequestException as exc:
            if attempt < max_attempts:
                wait = 2 ** attempt
                print(f"    Error: {exc} — retrying in {wait}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait)
            else:
                raise


def _run_batch(batch: dict, dry_run: bool) -> tuple[int, int, list[str]]:
    """Download one batch. Returns (downloaded, skipped, failed_filenames)."""
    target_dir: Path = batch["dir"]
    images: list[dict] = batch["images"]

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = 0
    failed: list[str] = []

    for i, img in enumerate(images):
        dest = target_dir / img["filename"]

        if dest.exists():
            print(f"  skip  {img['filename']}")
            skipped += 1
            continue

        if dry_run:
            print(f"  [dry] {img['filename']}  ←  {img['url']}")
            downloaded += 1
            continue

        print(f"  fetch {img['filename']}  ({i + 1}/{len(images)})")
        try:
            _download_with_retry(img["url"], dest)
            downloaded += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED: {exc}")
            failed.append(img["filename"])

        if i < len(images) - 1:
            time.sleep(0.5)  # courtesy delay between Wikimedia requests

    return downloaded, skipped, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be fetched without downloading.")
    args = parser.parse_args()

    empty = [b["name"] for b in _BATCHES if not b["images"]]
    if empty:
        raise SystemExit(
            f"ERROR: batch(es) not yet populated: {', '.join(empty)}\n"
            "Curate images per docs/plans/demo-corpus.md, then populate BATCH1_IMAGES / BATCH2_IMAGES."
        )

    _assert_no_seed_overlap()

    total_dl = total_sk = 0
    all_failed: list[str] = []

    for batch in _BATCHES:
        print(f"\n{batch['name']} → {batch['dir']}")
        dl, sk, failed = _run_batch(batch, dry_run=args.dry_run)
        total_dl += dl
        total_sk += sk
        all_failed.extend(failed)
        print(f"  {dl} downloaded, {sk} skipped, {len(failed)} failed")

    print(f"\nTotal: {total_dl} downloaded, {total_sk} skipped", end="")
    if all_failed:
        print(f", {len(all_failed)} FAILED: {all_failed}")
        sys.exit(1)
    else:
        print()


if __name__ == "__main__":
    main()
