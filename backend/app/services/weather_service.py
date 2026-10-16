"""
Weather Provider Service — Open-Meteo Integration
Fetches, normalizes, caches, and stores weather forecasts for synthetic demonstration locations.
Uses Open-Meteo (free, open-source, no API key required).
"""
import hashlib
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any, Tuple

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.weather_models import Location, WeatherRecord
from app.schemas.weather_schemas import (
    WeatherDataPoint,
    WeatherCurrentResponse,
    WeatherForecastResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory TTL cache: { location_id: (data, retrieved_at_timestamp) }
# ---------------------------------------------------------------------------
_weather_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}


def _cache_key(location_id: str) -> str:
    return location_id


def _get_cached(location_id: str) -> Optional[Tuple[List[Dict[str, Any]], float]]:
    """Return the cached entry (possibly expired) or None. Callers check age with classify_freshness."""
    return _weather_cache.get(_cache_key(location_id))


# One lock per location so concurrent requests share a single provider call
_fetch_locks: Dict[str, threading.Lock] = {}
_fetch_locks_guard = threading.Lock()


# After a failed fetch, don't retry a location for a while (avoids hammering a rate-limited provider)
FAILURE_BACKOFF_SECONDS = 60
_failed_until: Dict[str, float] = {}


def _in_backoff(location_id: str) -> bool:
    return time.time() < _failed_until.get(location_id, 0)


def _lock_for(location_id: str) -> threading.Lock:
    with _fetch_locks_guard:
        return _fetch_locks.setdefault(location_id, threading.Lock())


def _set_cache(location_id: str, data: List[Dict[str, Any]]) -> float:
    ts = time.time()
    _weather_cache[_cache_key(location_id)] = (data, ts)
    return ts


def classify_freshness(retrieved_at_ts: Optional[float]) -> str:
    """Classify data freshness based on age relative to configured TTL."""
    if retrieved_at_ts is None:
        return "UNKNOWN"
    age = time.time() - retrieved_at_ts
    if age <= settings.WEATHER_CACHE_TTL_SECONDS:
        return "FRESH"
    elif age <= settings.WEATHER_CACHE_TTL_SECONDS * settings.WEATHER_STALE_MULTIPLIER:
        return "STALE"
    return "UNKNOWN"


def _hash_response(data: Any) -> str:
    """Produce a SHA-256 hash of the raw response for deduplication."""
    raw = str(data).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Open-Meteo HTTP Client
# ---------------------------------------------------------------------------

# Open-Meteo variable name -> normalized field name
_HOURLY_FIELDS = {
    "temperature_2m": "temperature_celsius",
    "precipitation": "precipitation_mm",
    "wind_speed_10m": "wind_speed_kmh",
    "weather_code": "weather_code",
    "wind_gusts_10m": "wind_gust_kmh",
    "wind_direction_10m": "wind_direction_deg",
    "visibility": "visibility_m",
    "cloud_cover": "cloud_cover_pct",
    "relative_humidity_2m": "relative_humidity_pct",
    "pressure_msl": "pressure_hpa",
    "dew_point_2m": "dew_point_celsius",
}
_HOURLY_VARIABLES = list(_HOURLY_FIELDS)
# Optional fields passed through untouched from provider to API response
EXTRA_FIELDS = [
    "wind_gust_kmh", "wind_direction_deg", "visibility_m", "cloud_cover_pct",
    "relative_humidity_pct", "pressure_hpa", "dew_point_celsius",
]


def _to_utc_iso(t_str: str) -> str:
    """Open-Meteo returns naive timestamps when timezone=UTC; make the offset explicit."""
    if t_str.endswith("Z") or "+" in t_str[10:]:
        return t_str
    return f"{t_str}+00:00"


def _build_open_meteo_url(latitudes: List[float], longitudes: List[float]) -> str:
    """Forecast URL for one or more points (Open-Meteo accepts comma-separated coordinates)."""
    base = settings.WEATHER_PROVIDER_BASE_URL.rstrip("/")
    lats = ",".join(str(x) for x in latitudes)
    lons = ",".join(str(x) for x in longitudes)
    variables = ",".join(_HOURLY_VARIABLES)
    return f"{base}/forecast?latitude={lats}&longitude={lons}&hourly={variables}&forecast_days=2&timezone=UTC"


def _get_json(url: str) -> Any:
    timeout = httpx.Timeout(
        connect=float(settings.WEATHER_REQUEST_TIMEOUT_SECONDS),
        read=float(settings.WEATHER_REQUEST_TIMEOUT_SECONDS),
        write=5.0,
        pool=5.0,
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
        if response.status_code == 429:
            logger.warning("Weather provider rate limit hit (429)")
            raise WeatherProviderError("Weather provider rate limit exceeded. Retry later.")
        response.raise_for_status()
        return response.json()
    except WeatherProviderError:
        raise
    except httpx.TimeoutException:
        logger.error("Weather provider request timed out: %s", url)
        raise WeatherProviderError("Weather provider request timed out.")
    except httpx.HTTPStatusError as e:
        logger.error("Weather provider HTTP error: %s", e.response.status_code)
        raise WeatherProviderError(f"Weather provider returned HTTP {e.response.status_code}.")
    except httpx.RequestError as e:
        logger.error("Weather provider connection error: %s", str(e))
        raise WeatherProviderError(f"Weather provider connection error: {str(e)}")
    except ValueError as e:
        raise WeatherProviderError(f"Weather provider returned invalid JSON: {e}")


def _parse_hourly(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not hourly or "time" not in hourly:
        logger.error("Invalid weather provider response: missing 'hourly.time'")
        raise WeatherProviderError("Invalid weather provider response: missing hourly data.")

    units = payload.get("hourly_units", {})
    data_points = []
    for i, t_str in enumerate(hourly.get("time", [])):
        dp: Dict[str, Any] = {"forecast_timestamp": _to_utc_iso(t_str)}
        for var, field in _HOURLY_FIELDS.items():
            values = hourly.get(var) or []
            dp[field] = values[i] if i < len(values) else None
        data_points.append(dp)

    units_normalized = {
        "temperature": units.get("temperature_2m", "°C"),
        "precipitation": units.get("precipitation", "mm"),
        "wind_speed": units.get("wind_speed_10m", "km/h"),
    }
    return data_points, units_normalized


def fetch_weather_batch(
    coords: List[Tuple[float, float]],
) -> List[Tuple[List[Dict[str, Any]], Dict[str, str]]]:
    """
    One Open-Meteo request for several points; results are in the same order as `coords`.
    Raises WeatherProviderError on HTTP errors, timeouts, or invalid responses.
    """
    url = _build_open_meteo_url([c[0] for c in coords], [c[1] for c in coords])
    payload = _get_json(url)
    # A single point returns an object; several points return a list
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(coords):
        raise WeatherProviderError(f"Provider returned {len(items)} forecasts for {len(coords)} points.")
    return [_parse_hourly(item) for item in items]


def fetch_weather_from_provider(
    latitude: float,
    longitude: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Fetch the hourly forecast for one point. Returns (hourly_data_list, units_dict)."""
    return fetch_weather_batch([(latitude, longitude)])[0]


class WeatherProviderError(Exception):
    """Raised when the weather provider is unavailable or returns invalid data."""
    pass


# ---------------------------------------------------------------------------
# High-Level Service Functions
# ---------------------------------------------------------------------------

def _weather_code_to_condition(code: Optional[int]) -> Optional[str]:
    """Map WMO weather code to a human-readable condition string."""
    if code is None:
        return None
    code_map = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
        77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
        82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
    }
    return code_map.get(code, f"Code {code}")


def get_weather_for_location(
    db: Session,
    location: Location,
    force_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], str, Optional[float]]:
    """
    Get weather data for a location. Uses cache first, falls back to provider.
    Returns (data_points, freshness_status, retrieved_at_timestamp).
    Never treats missing data as safe.
    """
    cache_entry = _get_cached(location.id)
    if cache_entry and not force_refresh and classify_freshness(cache_entry[1]) == "FRESH":
        return cache_entry[0], "FRESH", cache_entry[1]

    with _lock_for(location.id):
        # Another request may have refreshed the cache while we waited for the lock
        cache_entry = _get_cached(location.id)
        if cache_entry and classify_freshness(cache_entry[1]) == "FRESH" and (
            not force_refresh or time.time() - cache_entry[1] < 5
        ):
            return cache_entry[0], "FRESH", cache_entry[1]
        if _in_backoff(location.id) and not force_refresh:
            return _fallback(cache_entry)
        return _fetch_and_store(location, cache_entry)


def _fallback(cache_entry) -> Tuple[List[Dict[str, Any]], str, Optional[float]]:
    """Serve the last good data, clearly marked, rather than nothing."""
    if cache_entry:
        data, ts = cache_entry
        return data, "STALE", ts
    return [], "UNKNOWN", None


def _needs_fetch(location_id: str) -> bool:
    entry = _get_cached(location_id)
    fresh = entry is not None and classify_freshness(entry[1]) == "FRESH"
    return not fresh and not _in_backoff(location_id)


def prefetch_weather(locations: List[Location]) -> None:
    """
    Warm the cache for many locations with a single provider request.
    Only locations without fresh data (and not in failure backoff) are fetched.
    """
    due = [loc for loc in locations if _needs_fetch(loc.id)]
    if not due:
        return
    try:
        results = fetch_weather_batch([(loc.latitude, loc.longitude) for loc in due])
    except WeatherProviderError as e:
        logger.warning("Batch weather fetch failed for %d locations: %s", len(due), e)
        for loc in due:
            _failed_until[loc.id] = time.time() + FAILURE_BACKOFF_SECONDS
        return
    for loc, (raw, units) in zip(due, results):
        _store(loc, raw, units)


def _fetch_and_store(
    location: Location,
    cache_entry: Optional[Tuple[List[Dict[str, Any]], float]],
) -> Tuple[List[Dict[str, Any]], str, Optional[float]]:
    try:
        raw_data, units = fetch_weather_from_provider(location.latitude, location.longitude)
    except WeatherProviderError as e:
        logger.warning("Provider error for location %s: %s", location.name, str(e))
        _failed_until[location.id] = time.time() + FAILURE_BACKOFF_SECONDS
        return _fallback(cache_entry)
    normalized, ts = _store(location, raw_data, units)
    return normalized, "FRESH", ts


def _store(
    location: Location,
    raw_data: List[Dict[str, Any]],
    units: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], float]:
    """Normalize a provider response, cache it and keep a history copy in the DB."""
    _failed_until.pop(location.id, None)
    now_utc = datetime.now(timezone.utc)
    resp_hash = _hash_response(raw_data)
    normalized = [
        {
            "forecast_timestamp": dp["forecast_timestamp"],
            "temperature_celsius": dp.get("temperature_celsius"),
            "precipitation_mm": dp.get("precipitation_mm"),
            "wind_speed_kmh": dp.get("wind_speed_kmh"),
            "weather_condition": _weather_code_to_condition(dp.get("weather_code")),
            "units": units,
            **{f: dp.get(f) for f in EXTRA_FIELDS},
        }
        for dp in raw_data
    ]
    ts = _set_cache(location.id, normalized)
    _persist_weather_records(location.id, normalized, resp_hash, now_utc, units)
    return normalized, ts


def _persist_weather_records(
    location_id: str,
    data_points: List[Dict[str, Any]],
    response_hash: str,
    retrieved_at: datetime,
    units: Dict[str, str],
) -> None:
    """
    Store a forecast snapshot for history. Uses its own short transaction so the
    SQLite write lock is released immediately instead of at the end of the request.
    Failure here never affects the weather response.
    """
    try:
        with SessionLocal() as session:
            exists = session.query(WeatherRecord.id).filter_by(
                location_id=location_id,
                raw_response_hash=response_hash,
            ).first()
            if exists:
                return

            for dp in data_points:
                try:
                    fc_ts = datetime.fromisoformat(dp["forecast_timestamp"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                session.add(WeatherRecord(
                    location_id=location_id,
                    provider="open-meteo",
                    forecast_timestamp=fc_ts,
                    retrieved_at=retrieved_at,
                    temperature_celsius=dp.get("temperature_celsius"),
                    precipitation_mm=dp.get("precipitation_mm"),
                    wind_speed_kmh=dp.get("wind_speed_kmh"),
                    weather_condition=dp.get("weather_condition"),
                    units_json=units,
                    freshness_status="FRESH",
                    raw_response_hash=response_hash,
                ))
            session.commit()
    except Exception as e:
        logger.error("Error persisting weather records: %s", str(e))


def get_current_weather(
    db: Session, location: Location
) -> WeatherCurrentResponse:
    """Get the most recent/current weather data point for a location."""
    data, freshness, ts = get_weather_for_location(db, location)

    current_dp = None
    if data:
        now_utc = datetime.now(timezone.utc)
        # Find the data point closest to now
        closest = None
        closest_diff = float("inf")
        for dp in data:
            try:
                fc_ts = datetime.fromisoformat(
                    dp["forecast_timestamp"].replace("Z", "+00:00")
                )
                diff = abs((fc_ts - now_utc).total_seconds())
                if diff < closest_diff:
                    closest_diff = diff
                    closest = dp
            except (ValueError, AttributeError):
                continue

        if closest:
            current_dp = WeatherDataPoint(
                forecast_timestamp=datetime.fromisoformat(
                    closest["forecast_timestamp"].replace("Z", "+00:00")
                ),
                temperature_celsius=closest.get("temperature_celsius"),
                precipitation_mm=closest.get("precipitation_mm"),
                wind_speed_kmh=closest.get("wind_speed_kmh"),
                weather_condition=closest.get("weather_condition"),
                units=closest.get("units", {}),
                **{f: closest.get(f) for f in EXTRA_FIELDS},
            )

    return WeatherCurrentResponse(
        location_id=location.id,
        location_name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        data=current_dp,
        freshness=freshness,
        retrieved_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
    )


def get_forecast_weather(
    db: Session, location: Location
) -> WeatherForecastResponse:
    """Get the full hourly forecast for a location."""
    data, freshness, ts = get_weather_for_location(db, location)

    hourly = []
    for dp in data:
        try:
            fc_ts = datetime.fromisoformat(
                dp["forecast_timestamp"].replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            continue
        hourly.append(WeatherDataPoint(
            forecast_timestamp=fc_ts,
            temperature_celsius=dp.get("temperature_celsius"),
            precipitation_mm=dp.get("precipitation_mm"),
            wind_speed_kmh=dp.get("wind_speed_kmh"),
            weather_condition=dp.get("weather_condition"),
            units=dp.get("units", {}),
            **{f: dp.get(f) for f in EXTRA_FIELDS},
        ))

    return WeatherForecastResponse(
        location_id=location.id,
        location_name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        forecast_points=hourly,
        freshness=freshness,
        retrieved_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
    )
