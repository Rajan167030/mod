"""
Unit tests for the Open-Meteo weather service and the NOAA METAR service.
HTTP is mocked by the autouse `mock_weather_providers` fixture in conftest.
"""
import time
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx

from app.core.config import settings
from app.services import weather_service
from app.services.metar_service import get_nearest_metar
from app.services.weather_service import (
    classify_freshness,
    fetch_weather_from_provider,
    get_current_weather,
    get_forecast_weather,
    get_weather_for_location,
)
from tests.conftest import AWC_PATTERN, OPEN_METEO_PATTERN

TTL = settings.WEATHER_CACHE_TTL_SECONDS


def _location(**kw):
    base = dict(id="loc-test-1", name="Test Station", latitude=34.15, longitude=77.58)
    base.update(kw)
    return SimpleNamespace(**base)


def _db():
    """Session stub: no stored records, accepts writes."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    return db


def test_classify_freshness():
    now = time.time()
    assert classify_freshness(now) == "FRESH"
    assert classify_freshness(now - (TTL - 10)) == "FRESH"
    assert classify_freshness(now - (TTL + 50)) == "STALE"
    assert classify_freshness(now - TTL * 3) == "UNKNOWN"
    assert classify_freshness(None) == "UNKNOWN"


def test_fetch_normalizes_all_fields_and_marks_utc():
    points, units = fetch_weather_from_provider(34.15, 77.58)
    assert len(points) == 48
    first = points[0]
    # Open-Meteo returns naive timestamps; the service must make UTC explicit
    assert first["forecast_timestamp"].endswith("+00:00")
    assert first["wind_gust_kmh"] == 22.0
    assert first["visibility_m"] == 20000
    assert units["wind_speed"] == "km/h"


def test_current_weather_picks_point_nearest_now():
    res = get_current_weather(_db(), _location())
    assert res.freshness == "FRESH"
    assert res.data is not None
    assert res.data.forecast_timestamp.tzinfo is not None
    assert res.data.wind_direction_deg == 270


def test_forecast_returns_hourly_points():
    res = get_forecast_weather(_db(), _location())
    assert res.location_id == "loc-test-1"
    assert len(res.forecast_points) == 48
    assert res.forecast_points[0].temperature_celsius == 8.0
    assert res.forecast_points[0].forecast_timestamp.tzinfo == timezone.utc


def test_provider_timeout_returns_no_data_not_fake_data(mock_weather_providers):
    mock_weather_providers.get(url__regex=OPEN_METEO_PATTERN).mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    data, freshness, ts = get_weather_for_location(_db(), _location(id="loc-timeout"))
    assert data == []
    assert freshness == "UNKNOWN"
    assert ts is None


def _age_cache(location_id: str, seconds: float) -> None:
    data, ts = weather_service._weather_cache[location_id]
    weather_service._weather_cache[location_id] = (data, ts - seconds)


def test_provider_failure_serves_stale_cache(mock_weather_providers):
    loc = _location(id="loc-cache")
    get_weather_for_location(_db(), loc)  # warm cache
    _age_cache(loc.id, 60)

    mock_weather_providers.get(url__regex=OPEN_METEO_PATTERN).mock(return_value=httpx.Response(503))
    data, freshness, _ = get_weather_for_location(_db(), loc, force_refresh=True)
    assert len(data) == 48
    assert freshness == "STALE"


def test_cache_avoids_second_request(mock_weather_providers):
    loc = _location(id="loc-cached-twice")
    get_weather_for_location(_db(), loc)
    get_weather_for_location(_db(), loc)
    calls = [c for c in mock_weather_providers.calls if "open-meteo" in str(c.request.url)]
    assert len(calls) == 1


def test_nearest_metar_parses_observation():
    res = get_nearest_metar(_location())
    obs = res.observation
    assert obs is not None
    assert obs.station_id == "VILH"
    assert obs.flight_category == "MVFR"
    assert obs.distance_km < 10
    assert obs.clouds[0].base_ft == 5000
    assert obs.raw_taf.startswith("TAF VILH")


def test_metar_outside_radius_reports_message(mock_weather_providers):
    res = get_nearest_metar(_location(id="loc-far", latitude=10.0, longitude=10.0))
    assert res.observation is None
    assert "No METAR" in res.message


def test_metar_provider_down_is_reported(mock_weather_providers):
    mock_weather_providers.get(url__regex=AWC_PATTERN).mock(side_effect=httpx.ConnectError("down"))
    res = get_nearest_metar(_location(id="loc-awc-down"))
    assert res.observation is None
    assert "unreachable" in res.message


def _open_meteo_calls(router):
    return [c for c in router.calls if "open-meteo" in str(c.request.url)]


def test_expired_cache_is_refetched(mock_weather_providers):
    """Data older than the TTL must be refreshed automatically, not served until someone clicks Refresh."""
    loc = _location(id="loc-expiry")
    get_weather_for_location(_db(), loc)
    _age_cache(loc.id, TTL + 1)

    data, freshness, _ = get_weather_for_location(_db(), loc)
    assert freshness == "FRESH"
    assert len(_open_meteo_calls(mock_weather_providers)) == 2


def test_concurrent_requests_share_one_provider_call(mock_weather_providers):
    from concurrent.futures import ThreadPoolExecutor

    loc = _location(id="loc-concurrent")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: get_weather_for_location(_db(), loc), range(8)))

    assert all(freshness == "FRESH" for _, freshness, _ in results)
    assert len(_open_meteo_calls(mock_weather_providers)) == 1


def test_prefetch_uses_one_request_for_many_sites(mock_weather_providers):
    locs = [_location(id=f"loc-batch-{i}", latitude=30 + i, longitude=70 + i) for i in range(6)]
    weather_service.prefetch_weather(locs)
    assert len(_open_meteo_calls(mock_weather_providers)) == 1

    # Every site is now served from cache without further provider calls
    for loc in locs:
        _, freshness, _ = get_weather_for_location(_db(), loc)
        assert freshness == "FRESH"
    assert len(_open_meteo_calls(mock_weather_providers)) == 1


def test_failed_site_is_not_refetched_during_backoff(mock_weather_providers):
    mock_weather_providers.get(url__regex=OPEN_METEO_PATTERN).mock(return_value=httpx.Response(429))
    loc = _location(id="loc-backoff")
    for _ in range(3):
        data, freshness, _ = get_weather_for_location(_db(), loc)
        assert data == [] and freshness == "UNKNOWN"
    assert len(_open_meteo_calls(mock_weather_providers)) == 1
