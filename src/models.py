"""Pydantic models for MongoDB document shapes."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# No extra="forbid": Gemini response_schema rejects additionalProperties:false
# (established in Steps 2/4 — same constraint applies here).
class QueueItem(BaseModel):
    asset_id: str
    queue_type: Literal["exploitation", "discovery"]
    rank: int
    product_route: Literal["poster", "tshirt", "social_only"] | None
    rationale: str


class ReviewQueue(BaseModel):
    event_id: str
    exploitation: list[QueueItem]
    discovery: list[QueueItem]
    strategy_summary: str


class AssetScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_score: float = Field(..., ge=0.0, le=1.0)
    merch_score: float = Field(..., ge=0.0, le=1.0)
    emotional_score: float = Field(..., ge=0.0, le=1.0)
    social_score: float = Field(..., ge=0.0, le=1.0)
    identity_score: float = Field(..., ge=0.0, le=1.0)


# No extra="forbid": Gemini response_schema rejects additionalProperties:false
# (verified empirically in Step 2 — same constraint applies to VisionScoringOutput).
class VisionScoringOutput(BaseModel):
    scores: AssetScores
    detected_subjects: list[str]


class Player(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: str
    name: str
    nationality: str
    team: str
    position: str
    notable_facts: list[str]
    career_milestones: str
    commercial_signal: Literal["high", "medium", "low"]


# Narrative schema models: extra="forbid" intentionally omitted — Gemini's
# response_schema rejects additionalProperties:false (verified empirically).
class KeyFigure(BaseModel):
    name: str
    team: str
    relevance: str
    grounded_facts: list[str]
    commercial_signal: Literal["high", "medium", "low"]


class HistoricalBaseline(BaseModel):
    outcome_type: str
    past_event_count: int
    top_product_route: str | None
    total_orders: int
    total_impressions: int
    notes: str


class EventNarrative(BaseModel):
    event_id: str
    narrative_angle: str
    key_figures: list[KeyFigure]
    commercial_timing: str
    historical_baseline: HistoricalBaseline


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
    event_narrative: "EventNarrative | None" = None


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    event_id: str
    content_url: str
    status: str = "ingested"
    upload_date: str
    product_route: str | None = None
    queue_type: str | None = None
    queue_rank: int | None = None
    queue_rationale: str | None = None
    embedding: list[float] | None = None
    scores: "AssetScores | None" = None
    detected_subjects: list[str] | None = None
    campaign_id: str | None = None
    similar_assets: list[str] | None = None


class SimilarAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    event_id: str
    similarity: float = Field(..., ge=0.0, le=1.0)
    product_route: str | None
    scores: dict[str, Any] | None


class SimilarityResult(BaseModel):
    asset_id: str
    neighbors: list[SimilarAsset]
    inferred_route: str | None


# No extra="forbid": Gemini response_schema rejects additionalProperties:false
# (same constraint as VisionScoringOutput / QueueItem — established in Steps 2/4/5).
class GeneratedCopy(BaseModel):
    headline: str
    caption: str
    hashtags: list[str]


class Campaign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    asset_id: str
    event_id: str
    product_type: Literal["poster", "tshirt"] | None
    generated_copy: GeneratedCopy
    platform_target: Literal["shopify", "printful", "social"]
    timing_recommendation: str
    status: str = "draft"
    created_at: str
    execution: dict | None = None


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    campaign_id: str
    asset_id: str
    status: str = "pending"
    reviewer_notes: str | None = None
    created_at: str
    decided_at: str | None = None
