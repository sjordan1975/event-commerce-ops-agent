"""Download demo event batch images to local paths for demo recording.

Two batches:
  Batch 1 — win/upset outcome  →  /tmp/wc-final/
  Batch 2 — draw outcome       →  /tmp/wc-draw/

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
    # TODO: populate after Wikimedia curation and similarity probing.
    # Target: 20–25 images — win/upset visual genre (celebrations, portraits, trophies).
    # Similarity target: 6–8 items landing >= 0.75 against the seeded corpus.
    # Example entry:
    # {
    #     "url": "https://upload.wikimedia.org/wikipedia/commons/...",
    #     "filename": "celebration_trophy_01.jpg",
    #     "tags": ["celebration", "team_shot"],
    #     "notes": "CC-BY-SA 4.0, Author Name",
    # },
]

BATCH2_IMAGES: list[dict] = [
    # TODO: populate after Wikimedia curation and similarity probing.
    # Target: 20–25 images — draw visual genre (match action, lineups, subdued reactions).
    # Similarity target: 2–3 items landing >= 0.75; remainder < 0.75.
    # Example entry:
    # {
    #     "url": "https://upload.wikimedia.org/wikipedia/commons/...",
    #     "filename": "draw_midfield_action_01.jpg",
    #     "tags": ["match_action"],
    #     "notes": "CC-BY-SA 4.0, Author Name",
    # },
]

_BATCHES = [
    {"name": "Batch 1 (win/upset)", "dir": Path("/tmp/wc-final"),  "images": BATCH1_IMAGES},
    {"name": "Batch 2 (draw)",      "dir": Path("/tmp/wc-draw"),   "images": BATCH2_IMAGES},
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
