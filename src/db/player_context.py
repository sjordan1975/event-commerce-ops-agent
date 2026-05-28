"""Internal MongoDB wrapper for the player_context collection."""

from src.db import _parse_docs_response, get_client
from src.models import Player


async def find_players_for_teams(home_team: str, away_team: str) -> list[Player]:
    """Return all Player records for both teams (plain name match, no vector search)."""
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "player_context",
        "filter": {"team": {"$in": [home_team, away_team]}},
    })
    docs = _parse_docs_response(envelope)
    return [Player.model_validate(d) for d in docs]
