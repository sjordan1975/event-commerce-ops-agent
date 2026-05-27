"""Pydantic models for MongoDB document shapes."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    name: str
    home_team: str
    away_team: str
    location: str | None
    start_date: str
    final_score: str
    outcome_type: Literal["upset_victory", "extra_time_win", "expected_win", "draw"]
    timeliness: float = Field(..., ge=0.0, le=1.0)
    ingested_at: str


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    event_id: str
    content_url: str
    status: str = "ingested"
    upload_date: str
    product_route: str | None = None
    queue_type: str | None = None
    embedding: list[float] | None = None
    scores: dict[str, Any] | None = None
    campaign_id: str | None = None
