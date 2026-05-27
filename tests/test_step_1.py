"""Unit tests for Step 1 internal wrappers and ingest_event_batch capability."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import build_valid_asset, build_valid_event


@pytest.mark.anyio
async def test_record_event():
    from src.db.events import record_event

    # Use a past start_date so timeliness stays in [0, 1]
    event = build_valid_event(start_date="2026-05-26T19:00:00Z")
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": []})

    with patch("src.db.events.get_client", return_value=mock_client):
        result = await record_event(event)

    assert result == event.event_id
    mock_client.call.assert_called_once()
    call_args = mock_client.call.call_args
    assert call_args[0][0] == "insert-many"
    payload = call_args[0][1]
    assert payload["collection"] == "events"
    assert payload["database"] == "event_commerce"
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["event_id"] == event.event_id


@pytest.mark.anyio
async def test_record_assets():
    from src.db.assets import record_assets

    assets = [
        build_valid_asset(asset_id="ast-001", content_url="/tmp/a.jpg"),
        build_valid_asset(asset_id="ast-002", content_url="/tmp/b.jpg"),
        build_valid_asset(asset_id="ast-003", content_url="/tmp/c.jpg"),
    ]
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": []})

    with patch("src.db.assets.get_client", return_value=mock_client):
        result = await record_assets("evt-001", assets)

    # Returns asset_ids in input order
    assert result == ["ast-001", "ast-002", "ast-003"]
    mock_client.call.assert_called_once()
    call_args = mock_client.call.call_args
    assert call_args[0][0] == "insert-many"
    payload = call_args[0][1]
    assert payload["collection"] == "assets"
    assert payload["database"] == "event_commerce"
    assert len(payload["documents"]) == 3
    # All have status="ingested"
    for doc in payload["documents"]:
        assert doc["status"] == "ingested"


@pytest.mark.anyio
async def test_ingest_event_batch():
    from src.capabilities.ingest import ingest_event_batch
    from src.errors import PreconditionError

    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": []})

    # Use a past start_date so compute_timeliness stays in [0, 1]
    valid_metadata = {
        "name": "Argentina vs France",
        "home_team": "Argentina",
        "away_team": "France",
        "final_score": "3-2",
        "start_date": "2026-05-26T19:00:00Z",
        "outcome_type": "upset_victory",
        "location": "Lusail Stadium",
    }
    images = ["/tmp/wc-final/01.jpg", "/tmp/wc-final/02.jpg"]

    with patch("src.db.events.get_client", return_value=mock_client), \
         patch("src.db.assets.get_client", return_value=mock_client):
        result = await ingest_event_batch(images, valid_metadata)

    assert "event_id" in result
    assert isinstance(result["event_id"], str)
    assert "asset_ids" in result
    assert isinstance(result["asset_ids"], list)
    assert len(result["asset_ids"]) == 2

    # Two insert-many calls: events then assets
    assert mock_client.call.call_count == 2
    calls = mock_client.call.call_args_list
    assert calls[0][0][1]["collection"] == "events"
    assert calls[1][0][1]["collection"] == "assets"

    # PreconditionError raised for missing required fields
    with pytest.raises(PreconditionError) as exc_info:
        await ingest_event_batch(images, {"name": "Test"})
    err = exc_info.value
    assert err.capability == "ingest_event_batch"
    assert err.context == "event_metadata"
    assert "home_team" in err.missing
    assert "outcome_type" in err.missing

    # PreconditionError raised for invalid outcome_type
    bad_metadata = dict(valid_metadata, outcome_type="blowout")
    with pytest.raises(PreconditionError) as exc_info2:
        await ingest_event_batch(images, bad_metadata)
    assert "outcome_type" in exc_info2.value.missing
