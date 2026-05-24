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
]

# ---------------------------------------------------------------------------
# Seed images — 40 CC-licensed photos from Wikimedia Commons
# ~10 per event; tags drive synthetic score generation
# ---------------------------------------------------------------------------

SEED_IMAGES = [
    # === wc2022-final-arg-fra (extra_time_win) ===
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/88/Argentina_3-3_Francia_-_Copa_Mundial_2022_-_Argentina_campe%C3%B3n_%28cropped%29.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["celebration", "portrait"],
        "description": "Argentina champion celebration portrait, WC2022 Final",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/1e/Argentina_3-3_Francia_-_Copa_Mundial_2022_-_Messi_patea_un_penal.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["goal_action", "portrait"],
        "description": "Messi penalty kick, WC2022 Final",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/2e/Argentina_3-3_Francia_-_Copa_Mundial_2022_-_Montiel_patea_el_penal_de_la_victoria.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["goal_action"],
        "description": "Montiel winning penalty, WC2022 Final",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/3/36/Celebraci%C3%B3n_del_partido_Argentina-Croacia.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["celebration", "team_shot"],
        "description": "Argentina team celebration after semifinal, WC2022",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e9/Semifinal_Argentina-Croacia.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["match_action"],
        "description": "Argentina vs Croatia semifinal action, WC2022",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/7d/Semifinal_del_mundial_2022.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["match_action"],
        "description": "WC2022 semifinal match action",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/65/Argentina_3-3_Francia_-_Copa_Mundial_2022_-_Argentina_campe%C3%B3n.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["celebration", "team_shot"],
        "description": "Argentina team lifting trophy, WC2022 Final",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/f2/2022_FIFA_World_Cup_France_4%E2%80%931_Australia_-_%2813%29.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["match_action"],
        "description": "France vs Australia match action, WC2022",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/60/Brazil_vs_Serbia_WC2022_Brazil_celebrating.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["celebration"],
        "description": "Brazil celebrating goal vs Serbia, WC2022",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/3/39/2022_FIFA_World_Cup_Korea_Uruguay_02.jpg",
        "event_id": "wc2022-final-arg-fra",
        "tags": ["match_action"],
        "description": "Korea vs Uruguay match action, WC2022",
    },
    # === wc2018-grp-kor-ger (upset_victory) ===
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/c/c4/2018_FIFA_WorldCup_Russia_Korea_vs_Sweden_%2841068302930%29.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Korea vs Sweden match action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e7/2018_FIFA_WorldCup_Russia_Korea_vs_Sweden_%2842160214874%29.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Korea vs Sweden action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/2a/Morocco_v_Iran_2018_FIFA_World_Cup_Match_3_%282%29.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Morocco vs Iran match action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/8a/Morocco_v_Iran_2018_FIFA_World_Cup_Match_3_%286%29.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Morocco vs Iran action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/0/00/2018_FIFA_World_Cup_Group_B_march_IRN-MAR_1.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Iran vs Morocco group match, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/ef/2018_FIFA_World_Cup_Group_B_march_IRN-MAR_14.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Iran vs Morocco match action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Croatia%27s_post-match_huddle_after_the_2018_FIFA_World_Cup_Final.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["celebration", "team_shot"],
        "description": "Croatia post-match huddle, WC2018 Final",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/c/cc/Russia_World_Cup_2018_in_Belgium_J7.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Russia vs Belgium match action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Russia_World_Cup_2018_in_Belgium_J1.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["match_action"],
        "description": "Russia vs Belgium match, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/c/c1/Lionel_Messi_20180626.jpg",
        "event_id": "wc2018-grp-kor-ger",
        "tags": ["portrait"],
        "description": "Lionel Messi portrait, WC2018",
    },
    # === wc2014-final-ger-arg (expected_win) ===
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/89/Germany_and_Argentina_face_off_in_the_final_of_the_World_Cup_2014_-2014-07-13_%285%29.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["match_action"],
        "description": "Germany vs Argentina World Cup Final 2014 action",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/7a/Germany_and_Argentina_face_off_in_the_final_of_the_World_Cup_2014_-2014-07-13_%2813%29.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["match_action"],
        "description": "Germany vs Argentina 2014 Final",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/f8/Brazil_and_Colombia_match_at_the_FIFA_World_Cup_2014-07-04_%289%29.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["match_action"],
        "description": "Brazil vs Colombia match action, WC2014",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/23/Brazil_and_Croatia_match_at_the_FIFA_World_Cup_2014-06-12_%2802%29.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["match_action"],
        "description": "Brazil vs Croatia match action, WC2014",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e2/Uruguay_-_Costa_Rica_FIFA_World_Cup_2014_%2817%29.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["match_action"],
        "description": "Uruguay vs Costa Rica match, WC2014",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/63/Lionel_Messi_celebrating_after_scoring_a_goal_against_Iran_at_the_2014_FIFA_World_Cup.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["celebration", "portrait"],
        "description": "Messi celebrating goal vs Iran, WC2014",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/72/James_Rodriguez.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["portrait"],
        "description": "James Rodriguez portrait, WC2014",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/4/44/Cristiano_Ronaldo_0876.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["portrait"],
        "description": "Cristiano Ronaldo match portrait",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/d0/Argentina_u20_v_poland_celebration.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["celebration", "team_shot"],
        "description": "Argentina team celebration after win vs Poland",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/25/2022_FIFA_World_Cup_Match_17%2C_Iran_v_Wales_-_03.jpg",
        "event_id": "wc2014-final-ger-arg",
        "tags": ["match_action"],
        "description": "Iran vs Wales match action, WC2022",
    },
    # === wc2018-grp-esp-por (draw) ===
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/c/c0/Spain_and_Portugal_match_at_the_FIFA_World_Cup_2010-06-29.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Spain vs Portugal match action, WC2010",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e5/FIFA_World_Cup_2010_Netherlands_Uruguay_6.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Netherlands vs Uruguay semifinal, WC2010",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/4/4a/FIFA_World_Cup_2010_Brazil_North_Korea_11.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Brazil vs North Korea group match, WC2010",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/db/FIFA_World_Cup_2010_Brazil_North_Korea_1.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Brazil vs North Korea match action, WC2010",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/88/Maradona_1986_vs_italy.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action", "portrait"],
        "description": "Maradona in action vs Italy, WC1986",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/fa/Russia_World_Cup_2018_in_Belgium_J3.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Russia vs Belgium match, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/5/53/Russia_World_Cup_2018_in_Belgium_J4.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Russia vs Belgium action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/5/55/Russia_World_Cup_2018_in_Belgium_J5.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Russia vs Belgium match action, WC2018",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/d5/Black_Stars_fans_%E2%80%93_Ghana_national_football_team_fans_goal_celebration_%282010_FIFA_World_Cup%29.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["fans", "celebration"],
        "description": "Ghana fans celebrating goal, WC2010",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/4/49/FIFA_World_Cup_2006%2C_Iran_0-2_Portugal_%2811%29.jpg",
        "event_id": "wc2018-grp-esp-por",
        "tags": ["match_action"],
        "description": "Iran vs Portugal match action, WC2006",
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


def assign_product_route(scores: dict) -> str | None:
    """Assign product route from score profile. Mirrors the Step 4 routing logic."""
    if scores["merch_score"] > 0.65 and scores["quality_score"] > 0.70:
        return "poster"
    if scores["identity_score"] > 0.65 and scores["quality_score"] > 0.65:
        return "tshirt"
    if scores["social_score"] > 0.65 or scores["emotional_score"] > 0.70:
        return "social_only"
    return None


def generate_performance(
    asset_id: str,
    campaign_id: str,
    event_id: str,
    product_route: str | None,
    scores: dict,
    rng: random.Random,
) -> dict:
    """Generate channel-split performance metrics correlated to asset scores and route.

    poster/tshirt → shopify + printful metrics
    social_only   → social metrics only
    null          → all zeros
    Window: rolling 7 days from published_at (per MVP assumptions).
    """
    noise = rng.uniform(0.7, 1.3)
    merch_factor = (scores["merch_score"] + scores["quality_score"]) / 2
    social_factor = (scores["social_score"] + scores["emotional_score"]) / 2

    shopify: dict = {"views": 0, "orders": 0, "revenue_usd": 0.00}
    printful: dict = {"units_fulfilled": 0}
    social: dict = {"impressions": 0, "saves": 0}

    if product_route in ("poster", "tshirt"):
        orders = max(1, int(merch_factor * 14 * noise))
        shopify = {
            "views": orders * int(rng.uniform(8, 22)),
            "orders": orders,
            "revenue_usd": round(orders * rng.uniform(18.0, 42.0), 2),
        }
        printful = {"units_fulfilled": max(0, orders - int(rng.uniform(0, 2)))}
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
            "printful": printful,
            "social": social,
        },
        "window_days": 7,
        "recorded_at": "2023-06-01T10:00:00Z",
    }


def is_seeded(db) -> bool:
    """Return True if any seed event already exists in the events collection."""
    seed_ids = [e["event_id"] for e in SEED_EVENTS]
    return db.events.count_documents({"event_id": {"$in": seed_ids}}) > 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not MONGODB_URI:
        print("Error: MONGODB_URI is not set.", file=sys.stderr)
        sys.exit(1)
    if not GOOGLE_API_KEY:
        print("Error: GOOGLE_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]

    if is_seeded(db):
        print("Seed data already present — nothing to do.")
        client.close()
        return

    genai_client = genai.Client(api_key=GOOGLE_API_KEY)
    rng = random.Random(42)

    # Insert events
    for event in SEED_EVENTS:
        event_doc = {k: v for k, v in event.items() if k != "hours_to_ingest"}
        event_doc["timeliness"] = compute_timeliness(event["outcome_type"], event["hours_to_ingest"])
        db.events.insert_one(event_doc)
        print(f"  inserted event: {event['event_id']} ({event['outcome_type']})")

    # Insert assets and collect performance docs
    performance_docs = []
    for i, image in enumerate(SEED_IMAGES):
        print(f"  [{i + 1}/{len(SEED_IMAGES)}] embedding: {image['description']}")
        embedding = embed_image(genai_client, image["url"])
        scores = generate_scores(image["tags"], rng)
        product_route = assign_product_route(scores)
        asset_id = str(uuid.uuid4())
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
            "scored_at": "2023-01-01T01:00:00Z",
            "published_at": "2023-01-01T02:00:00Z",
        })

        performance_docs.append(
            generate_performance(asset_id, campaign_id, image["event_id"], product_route, scores, rng)
        )

    db.performance.insert_many(performance_docs)

    # Insert player_context
    player_docs = [{"player_id": str(uuid.uuid4()), **p} for p in SEED_PLAYERS]
    db.player_context.insert_many(player_docs)

    print(f"\n  {len(SEED_EVENTS)} events inserted")
    print(f"  {len(SEED_IMAGES)} assets inserted")
    print(f"  {len(performance_docs)} performance records inserted")
    print(f"  {len(player_docs)} player_context records inserted")
    print("\nDone.")
    client.close()


if __name__ == "__main__":
    main()
