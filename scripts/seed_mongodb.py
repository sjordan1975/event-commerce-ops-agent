"""
Seed event_commerce with historical World Cup campaign data.

Creates 4 past events (one per outcome_type), 40 assets with real
gemini-embedding-2 embeddings, and corresponding performance records.
Idempotent — exits cleanly if seed events already exist.

Usage:
    python scripts/seed_mongodb.py

Requires:
    MONGODB_URI    — Atlas connection string
    GOOGLE_API_KEY — for gemini-embedding-2 calls
"""

import os
import sys
import uuid
import random

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai
from google.genai import types as genai_types

from seed_images import SEED_IMAGES

load_dotenv()

MONGODB_URI = os.environ.get("MONGODB_URI")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
DB_NAME = "event_commerce"
EMBED_MODEL = "gemini-embedding-2"

TIMELINESS_BASE = {
    "upset_victory": 0.95,
    "extra_time_win": 0.85,
    "expected_win": 0.60,
    "draw": 0.40,
}

# ---------------------------------------------------------------------------
# Seed events — one per outcome_type enum value
# ---------------------------------------------------------------------------

SEED_EVENTS = [
    {
        "event_id": "wc2022-final-arg-fra",
        "name": "Argentina vs France",
        "home_team": "Argentina",
        "away_team": "France",
        "location": "Lusail Stadium, Qatar",
        "start_date": "2022-12-18T15:00:00Z",
        "final_score": "Argentina 3-3 France (AET, 4-2 pens)",
        "outcome_type": "extra_time_win",
        "hours_to_ingest": 2.5,
        "ingested_at": "2022-12-18T17:30:00Z",
    },
    {
        "event_id": "wc2018-grp-kor-ger",
        "name": "Korea Republic vs Germany",
        "home_team": "Korea Republic",
        "away_team": "Germany",
        "location": "Kazan Arena, Russia",
        "start_date": "2018-06-27T14:00:00Z",
        "final_score": "Korea Republic 2-0 Germany",
        "outcome_type": "upset_victory",
        "hours_to_ingest": 3.0,
        "ingested_at": "2018-06-27T17:00:00Z",
    },
    {
        "event_id": "wc2014-final-ger-arg",
        "name": "Germany vs Argentina",
        "home_team": "Germany",
        "away_team": "Argentina",
        "location": "Maracanã, Rio de Janeiro",
        "start_date": "2014-07-13T16:00:00Z",
        "final_score": "Germany 1-0 Argentina (AET)",
        "outcome_type": "expected_win",
        "hours_to_ingest": 2.0,
        "ingested_at": "2014-07-13T18:00:00Z",
    },
    {
        "event_id": "wc2018-grp-esp-por",
        "name": "Spain vs Portugal",
        "home_team": "Spain",
        "away_team": "Portugal",
        "location": "Fisht Stadium, Sochi",
        "start_date": "2018-06-15T18:00:00Z",
        "final_score": "Spain 3-3 Portugal",
        "outcome_type": "draw",
        "hours_to_ingest": 2.5,
        "ingested_at": "2018-06-15T20:30:00Z",
    },
]

# ---------------------------------------------------------------------------
# Seed players — key squad members for each team in seed events
# Teams covered: Argentina, France, Germany, Korea Republic, Spain, Portugal
# commercial_signal: editorial pre-rating, not computed by agent
# ---------------------------------------------------------------------------

SEED_PLAYERS = [
    # Argentina
    {
        "name": "Lionel Messi",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Forward",
        "notable_facts": [
            "2022 World Cup winner and Golden Ball winner",
            "All-time leading scorer in World Cup finals history",
            "Scored twice and converted a penalty in the 2022 WC Final vs France",
            "5th World Cup appearance in 2022",
        ],
        "career_milestones": "2022 World Cup winner; 8× Ballon d'Or; all-time Argentina top scorer",
        "commercial_signal": "high",
    },
    {
        "name": "Julián Álvarez",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Forward",
        "notable_facts": [
            "Scored 4 goals at the 2022 World Cup including two in the semifinal vs Croatia",
            "Won the 2022 World Cup as a 22-year-old",
            "Formed tournament-winning strike partnership with Messi",
        ],
        "career_milestones": "2022 World Cup winner; 2022 UEFA Champions League winner with Manchester City",
        "commercial_signal": "medium",
    },
    {
        "name": "Ángel Di María",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Winger",
        "notable_facts": [
            "Scored the extra-time winner in the 2014 World Cup Final vs Germany",
            "Scored in the 2022 World Cup Final — his final international match",
            "Won Copa América 2021 and World Cup 2022 to complete international trophy set",
        ],
        "career_milestones": "2014 WC Final match-winner; 2022 WC winner; retired from international football after 2022 WC Final",
        "commercial_signal": "medium",
    },
    {
        "name": "Emiliano Martínez",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Goalkeeper",
        "notable_facts": [
            "Won Golden Glove at the 2022 World Cup",
            "Saved three penalties in the 2022 WC Final shootout vs France",
            "Key figure in Argentina's penalty shootout victories throughout the 2022 tournament",
        ],
        "career_milestones": "2022 World Cup winner and Golden Glove; Copa América 2021 winner",
        "commercial_signal": "medium",
    },
    # France
    {
        "name": "Kylian Mbappé",
        "nationality": "France",
        "team": "France",
        "position": "Forward",
        "notable_facts": [
            "Scored a hat-trick in the 2022 World Cup Final, including two goals in 97 seconds",
            "Won the 2022 World Cup Golden Boot with 8 goals",
            "Won the 2018 World Cup aged 19",
            "Only second player after Pelé to score in a World Cup Final as a teenager",
        ],
        "career_milestones": "2018 and 2022 World Cup finalist; 2022 WC Golden Boot; youngest French WC scorer",
        "commercial_signal": "high",
    },
    {
        "name": "Antoine Griezmann",
        "nationality": "France",
        "team": "France",
        "position": "Forward",
        "notable_facts": [
            "Won the 2018 World Cup with France",
            "Scored in the 2018 World Cup Final vs Croatia",
            "Won the Golden Boot at Euro 2016",
        ],
        "career_milestones": "2018 World Cup winner; France all-time top scorer",
        "commercial_signal": "medium",
    },
    {
        "name": "Olivier Giroud",
        "nationality": "France",
        "team": "France",
        "position": "Forward",
        "notable_facts": [
            "Became France's all-time leading scorer in 2022",
            "Won the 2018 World Cup with France",
            "Scored 4 goals at the 2022 World Cup",
        ],
        "career_milestones": "2018 World Cup winner; France all-time record goalscorer (57 goals)",
        "commercial_signal": "medium",
    },
    # Germany
    {
        "name": "Mario Götze",
        "nationality": "Germany",
        "team": "Germany",
        "position": "Attacking Midfielder",
        "notable_facts": [
            "Scored the winning goal in extra time of the 2014 World Cup Final vs Argentina",
            "Entered the 2014 WC Final as a substitute and scored with a volley in the 113th minute",
            "Was 22 years old when he won the World Cup",
        ],
        "career_milestones": "2014 World Cup winner and Final match-winner",
        "commercial_signal": "medium",
    },
    {
        "name": "Thomas Müller",
        "nationality": "Germany",
        "team": "Germany",
        "position": "Forward",
        "notable_facts": [
            "Won the 2014 World Cup with Germany",
            "Won the Golden Boot at the 2010 World Cup with 5 goals",
            "Part of the Germany squad that beat Brazil 7-1 in the 2014 WC semifinal",
            "One of the most prolific World Cup scorers in German history",
        ],
        "career_milestones": "2014 World Cup winner; 2010 WC Golden Boot; 10 World Cup goals across 4 tournaments",
        "commercial_signal": "medium",
    },
    {
        "name": "Manuel Neuer",
        "nationality": "Germany",
        "team": "Germany",
        "position": "Goalkeeper",
        "notable_facts": [
            "Won the 2014 World Cup with Germany",
            "Won the Golden Glove at the 2014 World Cup",
            "Considered one of the greatest sweeper-keepers of all time",
        ],
        "career_milestones": "2014 World Cup winner and Golden Glove; long-time Germany captain",
        "commercial_signal": "medium",
    },
    # Korea Republic
    {
        "name": "Son Heung-min",
        "nationality": "South Korea",
        "team": "Korea Republic",
        "position": "Forward",
        "notable_facts": [
            "South Korea's all-time leading scorer",
            "Shared the Premier League Golden Boot in 2021–22",
            "Captain of the Korea Republic national team",
            "Scored in the 2022 World Cup group stage",
        ],
        "career_milestones": "Korea Republic all-time top scorer; 2022 Premier League Golden Boot",
        "commercial_signal": "high",
    },
    {
        "name": "Kim Min-jae",
        "nationality": "South Korea",
        "team": "Korea Republic",
        "position": "Centre-back",
        "notable_facts": [
            "Named Serie A Defender of the Year in 2022–23 with Napoli",
            "Key figure in Korea Republic's 2022 World Cup round-of-16 run",
            "Moved to Bayern Munich in 2023",
        ],
        "career_milestones": "2022 Serie A champion with Napoli; 2022–23 Serie A Defender of the Year",
        "commercial_signal": "medium",
    },
    # Spain
    {
        "name": "Sergio Ramos",
        "nationality": "Spain",
        "team": "Spain",
        "position": "Centre-back",
        "notable_facts": [
            "Part of Spain's historic 2010 World Cup winning squad",
            "Won Euro 2008, 2012 and World Cup 2010 with Spain",
            "Spain captain known for leadership and set-piece goals",
        ],
        "career_milestones": "2010 World Cup winner; 2× European Champion with Spain",
        "commercial_signal": "medium",
    },
    {
        "name": "David Silva",
        "nationality": "Spain",
        "team": "Spain",
        "position": "Midfielder",
        "notable_facts": [
            "Part of Spain's dominant era — World Cup 2010, Euro 2008 and Euro 2012 winner",
            "One of the most decorated Spanish midfielders of his generation",
            "Known for technical precision and creative play",
        ],
        "career_milestones": "2010 World Cup winner; 2× European Champion with Spain",
        "commercial_signal": "medium",
    },
    # Portugal
    {
        "name": "Cristiano Ronaldo",
        "nationality": "Portugal",
        "team": "Portugal",
        "position": "Forward",
        "notable_facts": [
            "Scored a hat-trick in Portugal's 3–3 draw vs Spain at the 2018 World Cup",
            "All-time top scorer in men's international football",
            "Won Euro 2016 with Portugal",
            "5× Ballon d'Or winner",
        ],
        "career_milestones": "Euro 2016 winner; all-time men's international top scorer; 5× Ballon d'Or",
        "commercial_signal": "high",
    },
    {
        "name": "Bruno Fernandes",
        "nationality": "Portugal",
        "team": "Portugal",
        "position": "Attacking Midfielder",
        "notable_facts": [
            "Portugal's creative engine and penalty taker",
            "Scored at the 2022 World Cup including a penalty vs Uruguay",
            "Manchester United captain",
        ],
        "career_milestones": "Regular Portugal starter since 2019; key figure in 2022 World Cup campaign",
        "commercial_signal": "medium",
    },
    # Croatia — added for 2018 WC Final demo batch (Batch 1)
    {
        "name": "Luka Modrić",
        "nationality": "Croatia",
        "team": "Croatia",
        "position": "Midfielder",
        "notable_facts": [
            "Won the FIFA Best Men's Player and Ballon d'Or in 2018 after leading Croatia to the World Cup Final",
            "Scored in the 2018 World Cup Final vs France",
            "Won the 2018 WC Golden Ball (best player of the tournament)",
            "Long-time Real Madrid and Croatia captain",
        ],
        "career_milestones": "2018 WC Golden Ball; 2018 Ballon d'Or; 6× UEFA Champions League winner with Real Madrid",
        "commercial_signal": "high",
    },
    {
        "name": "Ivan Perišić",
        "nationality": "Croatia",
        "team": "Croatia",
        "position": "Winger",
        "notable_facts": [
            "Scored the equaliser in the 2018 World Cup Final vs France",
            "Reached the 2022 World Cup Final with Croatia, losing to Argentina",
            "One of the most capped Croatian players of all time",
        ],
        "career_milestones": "2018 and 2022 World Cup finalist; scored in 2018 WC Final",
        "commercial_signal": "medium",
    },
    {
        "name": "Ante Rebić",
        "nationality": "Croatia",
        "team": "Croatia",
        "position": "Forward",
        "notable_facts": [
            "Scored Croatia's first goal in the 2018 World Cup Final vs France",
            "Part of the Croatia squad that reached the 2018 WC Final",
            "Known for physical, direct forward play",
        ],
        "career_milestones": "2018 World Cup finalist; scored in 2018 WC Final",
        "commercial_signal": "medium",
    },
    # United States — added for 2022 USA vs Wales demo batch (Batch 2)
    {
        "name": "Christian Pulisic",
        "nationality": "American",
        "team": "United States",
        "position": "Forward",
        "notable_facts": [
            "Scored the match-winning goal vs Iran to send the USA through to the round of 16 at WC2022",
            "First American to score in a World Cup knockout round since 2010",
            "Captain of the United States national team",
            "Plays for AC Milan in Serie A",
        ],
        "career_milestones": "USMNT captain; WC2022 hero vs Iran; 2021 UEFA Champions League winner with Chelsea",
        "commercial_signal": "high",
    },
    {
        "name": "Tyler Adams",
        "nationality": "American",
        "team": "United States",
        "position": "Midfielder",
        "notable_facts": [
            "Named captain of the United States at WC2022 aged 23",
            "Won the ball for the decisive play in the USA's win over Iran at WC2022",
            "One of the most composed central midfielders in USMNT history",
        ],
        "career_milestones": "USMNT captain at WC2022; played in Premier League with Bournemouth and Leeds",
        "commercial_signal": "medium",
    },
    {
        "name": "Matt Turner",
        "nationality": "American",
        "team": "United States",
        "position": "Goalkeeper",
        "notable_facts": [
            "Starting goalkeeper for the United States at WC2022",
            "Made key saves in the group stage including the match vs Wales",
            "Plays in the Premier League",
        ],
        "career_milestones": "USMNT starting GK at WC2022; Premier League experience",
        "commercial_signal": "low",
    },
    # Wales — added for 2022 USA vs Wales demo batch (Batch 2)
    {
        "name": "Gareth Bale",
        "nationality": "Welsh",
        "team": "Wales",
        "position": "Forward",
        "notable_facts": [
            "Scored the penalty that earned Wales a 1-1 draw vs USA at WC2022",
            "Wales' all-time leading scorer and most capped player",
            "5× UEFA Champions League winner with Real Madrid",
            "Led Wales to their first World Cup in 64 years in 2022",
        ],
        "career_milestones": "5× UCL winner; Wales all-time top scorer; led Wales to WC2022",
        "commercial_signal": "high",
    },
    {
        "name": "Brennan Johnson",
        "nationality": "Welsh",
        "team": "Wales",
        "position": "Forward",
        "notable_facts": [
            "Wales' most dynamic attacking threat at WC2022",
            "Scored for Wales in the 2022 World Cup",
            "Plays in the Premier League for Tottenham Hotspur",
            "Son of former Welsh international David Johnson",
        ],
        "career_milestones": "WC2022 participant; Premier League player with Spurs",
        "commercial_signal": "medium",
    },
    {
        "name": "Wayne Hennessey",
        "nationality": "Welsh",
        "team": "Wales",
        "position": "Goalkeeper",
        "notable_facts": [
            "Wales' most capped player of all time",
            "Starting goalkeeper for Wales at WC2022, their first World Cup in 64 years",
            "Veteran presence and leader in the Welsh squad",
        ],
        "career_milestones": "Wales all-time most capped player; WC2022 participant",
        "commercial_signal": "low",
    },
]



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_timeliness(outcome_type: str, hours_elapsed: float) -> float:
    """Compute timeliness score: base_score × 0.5^(hours_elapsed / 4)."""
    base = TIMELINESS_BASE[outcome_type]
    return round(base * (0.5 ** (hours_elapsed / 4)), 4)


WIKIMEDIA_HEADERS = {
    "User-Agent": "realtime-event-commerce-ops-agent/0.1 (https://github.com/example/repo; seed-script)"
}


def embed_image(client: genai.Client, url: str) -> list[float]:
    """Fetch image bytes from URL and return a gemini-embedding-2 vector (3072-dim)."""
    response = requests.get(url, headers=WIKIMEDIA_HEADERS, timeout=30)
    response.raise_for_status()
    mime_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
    part = genai_types.Part.from_bytes(data=response.content, mime_type=mime_type)
    result = client.models.embed_content(model=EMBED_MODEL, contents=[part])
    return list(result.embeddings[0].values)


def generate_scores(tags: list[str], rng: random.Random) -> dict:
    """Generate synthetic scores correlated to image content tags. All values 0–1."""
    scores = {
        "quality_score": rng.uniform(0.55, 0.92),
        "emotional_score": rng.uniform(0.45, 0.75),
        "social_score": rng.uniform(0.45, 0.75),
        "merch_score": rng.uniform(0.35, 0.70),
        "identity_score": rng.uniform(0.40, 0.70),
    }
    if "celebration" in tags:
        scores["emotional_score"] = min(1.0, scores["emotional_score"] + 0.18)
        scores["social_score"] = min(1.0, scores["social_score"] + 0.12)
    if "goal_action" in tags:
        scores["emotional_score"] = min(1.0, scores["emotional_score"] + 0.14)
    if "portrait" in tags:
        scores["identity_score"] = min(1.0, scores["identity_score"] + 0.18)
        scores["merch_score"] = min(1.0, scores["merch_score"] + 0.08)
    if "team_shot" in tags:
        scores["identity_score"] = min(1.0, scores["identity_score"] + 0.05)
        scores["merch_score"] = max(0.0, scores["merch_score"] - 0.08)
    if "fans" in tags:
        scores["social_score"] = min(1.0, scores["social_score"] + 0.05)
        scores["merch_score"] = max(0.0, scores["merch_score"] - 0.18)
        scores["identity_score"] = max(0.0, scores["identity_score"] - 0.12)
    return {k: round(v, 4) for k, v in scores.items()}



def generate_performance(
    asset_id: str,
    campaign_id: str,
    event_id: str,
    product_route: str | None,
    scores: dict,
    rng: random.Random,
) -> dict:
    """Generate channel-split performance metrics correlated to asset scores and route.

    poster/tshirt → shopify metrics
    social_only   → social metrics only
    null          → all zeros
    Window: rolling 7 days from publish time (per MVP assumptions).
    """
    noise = rng.uniform(0.7, 1.3)
    merch_factor = (scores["merch_score"] + scores["quality_score"]) / 2
    social_factor = (scores["social_score"] + scores["emotional_score"]) / 2

    shopify: dict = {"views": 0, "orders": 0, "revenue_usd": 0.00}
    social: dict = {"impressions": 0, "saves": 0}

    if product_route in ("poster", "tshirt"):
        orders = max(1, int(merch_factor * 14 * noise))
        shopify = {
            "views": orders * int(rng.uniform(8, 22)),
            "orders": orders,
            "revenue_usd": round(orders * rng.uniform(18.0, 42.0), 2),
        }
    elif product_route == "social_only":
        impressions = int(social_factor * 8000 * noise)
        social = {
            "impressions": impressions,
            "saves": int(impressions * rng.uniform(0.02, 0.06)),
        }

    return {
        "performance_id": str(uuid.uuid4()),
        "asset_id": asset_id,
        "campaign_id": campaign_id,
        "event_id": event_id,
        "metrics": {
            "shopify": shopify,
            "social": social,
        },
        "window_days": 7,
        "recorded_at": "2023-06-01T10:00:00Z",
    }


def is_seeded(db) -> bool:
    """Return True if any seed event already exists in the events collection."""
    seed_ids = [e["event_id"] for e in SEED_EVENTS]
    return db.events.count_documents({"event_id": {"$in": seed_ids}}) > 0


def patch_routes(db) -> None:
    """Patch product_route on existing seed assets to match the curated fixture.

    Looks up each seed asset by content_url and updates product_route if it
    differs from the fixture value. Also updates the corresponding performance
    record's metrics to match the new route (regenerated with a fixed rng so
    results are deterministic on repeated runs). No re-embedding — safe to run
    against a live Atlas corpus.
    """
    url_to_image = {img["url"]: img for img in SEED_IMAGES}

    seed_event_ids = [e["event_id"] for e in SEED_EVENTS]
    assets = list(db.assets.find(
        {"event_id": {"$in": seed_event_ids}},
        {"asset_id": 1, "content_url": 1, "product_route": 1, "campaign_id": 1},
    ))

    if not assets:
        print("No seed assets found — run seed_mongodb.py first.")
        return

    updated = 0
    skipped = 0

    print(f"Checking {len(assets)} seed assets ...")
    for asset in assets:
        url = asset["content_url"]
        image = url_to_image.get(url)
        if not image:
            continue

        new_route = image["product_route"]
        current_route = asset.get("product_route")

        if new_route == current_route:
            skipped += 1
            continue

        asset_id = asset["asset_id"]
        campaign_id = asset.get("campaign_id", str(uuid.uuid4()))
        rng = random.Random(asset_id)  # per-asset seed — deterministic, repeatable
        scores = generate_scores(image["tags"], rng)
        new_metrics = generate_performance(
            asset_id, campaign_id, image["event_id"], new_route, scores, rng
        )

        db.assets.update_one(
            {"asset_id": asset_id},
            {"$set": {"product_route": new_route}},
        )
        db.performance.update_one(
            {"asset_id": asset_id},
            {"$set": {"metrics": new_metrics["metrics"]}},
        )

        label = url.split("/")[-1][:55]
        print(f"  {label}: {current_route!r} → {new_route!r}")
        updated += 1

    print(f"\n  {updated} assets updated, {skipped} already correct.")
    print("Done.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def vector_only(db, genai_client: genai.Client) -> None:
    """Re-embed any asset in the corpus that is missing an embedding.

    Fail-fast: if an image is unreachable, aborts with the asset_id in the error.
    """
    assets = list(db.assets.find({"embedding": None}, {"asset_id": 1, "content_url": 1}))
    if not assets:
        print("All assets already have embeddings — nothing to do.")
        return
    print(f"Re-embedding {len(assets)} assets without embeddings ...")
    for asset in assets:
        asset_id = asset["asset_id"]
        url = asset["content_url"]
        try:
            print(f"  embedding asset {asset_id}: {url}")
            embedding = embed_image(genai_client, url)
        except Exception as exc:
            print(
                f"ERROR: failed to embed asset_id={asset_id!r} content_url={url!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        db.assets.update_one({"asset_id": asset_id}, {"$set": {"embedding": embedding}})
    print(f"Done. Embedded {len(assets)} assets.")


def add_images(db, genai_client: genai.Client) -> None:
    """Insert SEED_IMAGES entries not yet present in the assets collection.

    Idempotency: skips any URL already in assets.content_url.
    Uses per-asset RNG seeded from asset_id (matches patch_routes pattern).
    """
    existing_urls = {
        doc["content_url"]
        for doc in db.assets.find(
            {"event_id": {"$in": [e["event_id"] for e in SEED_EVENTS]}},
            {"content_url": 1, "_id": 0},
        )
    }

    new_images = [img for img in SEED_IMAGES if img["url"] not in existing_urls]

    if not new_images:
        print("All seed images already present — nothing to do.")
        return

    already = len(SEED_IMAGES) - len(new_images)
    print(f"Found {len(new_images)} new image(s) to insert ({already} already present, skipped).")

    performance_docs = []
    for i, image in enumerate(new_images):
        print(f"  [{i + 1}/{len(new_images)}] embedding: {image['description']}")
        asset_id = str(uuid.uuid4())
        try:
            embedding = embed_image(genai_client, image["url"])
        except Exception as exc:
            print(
                f"ERROR: failed to embed content_url={image['url']!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

        rng = random.Random(asset_id)
        scores = generate_scores(image["tags"], rng)
        product_route = image["product_route"]
        campaign_id = str(uuid.uuid4())

        db.assets.insert_one({
            "asset_id": asset_id,
            "event_id": image["event_id"],
            "content_url": image["url"],
            "status": "published",
            "product_route": product_route,
            "embedding": embedding,
            "scores": scores,
            "similar_assets": [],
            "campaign_id": campaign_id,
            "published_urls": {},
            "upload_date": "2023-01-01T00:00:00Z",
        })

        performance_docs.append(
            generate_performance(asset_id, campaign_id, image["event_id"], product_route, scores, rng)
        )

    db.performance.insert_many(performance_docs)

    print(f"\n  {len(new_images)} assets inserted")
    print(f"  {len(performance_docs)} performance records inserted")
    print("Done.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Seed event_commerce with historical World Cup data.")
    parser.add_argument(
        "--vector-only",
        action="store_true",
        help="Re-embed assets that are missing embeddings without re-seeding.",
    )
    parser.add_argument(
        "--patch-routes",
        action="store_true",
        help="Update product_route on existing seed assets to match the curated fixture. No re-embedding.",
    )
    parser.add_argument(
        "--add-images",
        action="store_true",
        help="Insert SEED_IMAGES entries not yet in Atlas (by content_url). Idempotent.",
    )
    args = parser.parse_args()

    if not MONGODB_URI:
        print("Error: MONGODB_URI is not set.", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]

    if args.patch_routes:
        patch_routes(db)
        client.close()
        return

    if not GOOGLE_API_KEY:
        print("Error: GOOGLE_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    genai_client = genai.Client(api_key=GOOGLE_API_KEY)

    if args.add_images:
        add_images(db, genai_client)
        client.close()
        return

    if args.vector_only:
        vector_only(db, genai_client)
        client.close()
        return

    if is_seeded(db):
        print("Seed data already present — nothing to do.")
        client.close()
        return

    rng = random.Random(42)

    # Insert events
    for event in SEED_EVENTS:
        event_doc = {k: v for k, v in event.items() if k != "hours_to_ingest"}
        event_doc["timeliness"] = compute_timeliness(event["outcome_type"], event["hours_to_ingest"])
        db.events.insert_one(event_doc)
        print(f"  inserted event: {event['event_id']} ({event['outcome_type']})")

    # Insert assets with embeddings (fail-fast on unreachable image)
    performance_docs = []
    for i, image in enumerate(SEED_IMAGES):
        print(f"  [{i + 1}/{len(SEED_IMAGES)}] embedding: {image['description']}")
        asset_id = str(uuid.uuid4())
        try:
            embedding = embed_image(genai_client, image["url"])
        except Exception as exc:
            print(
                f"ERROR: failed to embed asset_id={asset_id!r} content_url={image['url']!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

        scores = generate_scores(image["tags"], rng)
        product_route = image["product_route"]
        campaign_id = str(uuid.uuid4())

        db.assets.insert_one({
            "asset_id": asset_id,
            "event_id": image["event_id"],
            "content_url": image["url"],
            "status": "published",
            "product_route": product_route,
            "embedding": embedding,
            "scores": scores,
            "similar_assets": [],
            "campaign_id": campaign_id,
            "published_urls": {},
            "upload_date": "2023-01-01T00:00:00Z",
        })

        performance_docs.append(
            generate_performance(asset_id, campaign_id, image["event_id"], product_route, scores, rng)
        )

    db.performance.insert_many(performance_docs)

    # Insert player_context
    player_docs = [{"player_id": str(uuid.uuid4()), **p} for p in SEED_PLAYERS]
    db.player_context.insert_many(player_docs)

    print(f"\n  {len(SEED_EVENTS)} events inserted")
    print(f"  {len(SEED_IMAGES)} assets inserted (each with a 3072-dim embedding)")
    print(f"  {len(performance_docs)} performance records inserted")
    print(f"  {len(player_docs)} player_context records inserted")
    print("\nDone.")
    client.close()


if __name__ == "__main__":
    main()
