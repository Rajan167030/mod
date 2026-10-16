"""
METAR / TAF Service — NOAA Aviation Weather Center (aviationweather.gov) Data API.
Finds the reporting station nearest to a location and returns its latest observation.
Free, no API key required. Docs: https://aviationweather.gov/data/api/
"""
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.models.weather_models import Location
from app.schemas.weather_schemas import MetarCloudLayer, MetarObservation, MetarResponse

logger = logging.getLogger(__name__)

AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
METAR_SEARCH_RADIUS_KM = 150.0
METAR_CACHE_TTL_SECONDS = 600
_HPA_PER_INHG = 33.8639

# { location_id: (response, fetched_at_timestamp) }
_metar_cache: Dict[str, Tuple[MetarResponse, float]] = {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bbox(lat: float, lon: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.1))
    return f"{lat - dlat:.3f},{lon - dlon:.3f},{lat + dlat:.3f},{lon + dlon:.3f}"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_altimeter(value: Any) -> Optional[float]:
    """AWC reports altimeter in hPa for most stations, inHg for some (values ~30)."""
    alt = _num(value)
    if alt is None:
        return None
    return round(alt * _HPA_PER_INHG) if alt < 100 else alt


def _to_observation(raw: Dict[str, Any], distance_km: float) -> MetarObservation:
    obs_time = raw.get("obsTime")
    observed_at = (
        datetime.fromtimestamp(obs_time, tz=timezone.utc) if isinstance(obs_time, (int, float)) else None
    )
    wdir = raw.get("wdir")
    return MetarObservation(
        station_id=raw.get("icaoId", "????"),
        station_name=raw.get("name"),
        latitude=raw.get("lat"),
        longitude=raw.get("lon"),
        elevation_m=_num(raw.get("elev")),
        distance_km=round(distance_km, 1),
        observed_at=observed_at,
        raw_metar=raw.get("rawOb", ""),
        raw_taf=raw.get("rawTaf"),
        flight_category=raw.get("fltCat"),
        temperature_celsius=_num(raw.get("temp")),
        dew_point_celsius=_num(raw.get("dewp")),
        wind_direction_deg=_num(wdir),  # "VRB" -> None
        wind_speed_kt=_num(raw.get("wspd")),
        wind_gust_kt=_num(raw.get("wgst")),
        visibility=str(raw["visib"]) if raw.get("visib") is not None else None,
        altimeter_hpa=_parse_altimeter(raw.get("altim")),
        clouds=[
            MetarCloudLayer(cover=c.get("cover", ""), base_ft=c.get("base"))
            for c in (raw.get("clouds") or [])
        ],
    )


def _fetch_metars(bbox: str) -> List[Dict[str, Any]]:
    timeout = float(settings.WEATHER_REQUEST_TIMEOUT_SECONDS)
    params = {"bbox": bbox, "format": "json", "taf": "true", "hours": "3"}
    with httpx.Client(timeout=timeout) as client:
        response = client.get(AWC_METAR_URL, params=params)
    if response.status_code == 204:  # no stations in box
        return []
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def get_nearest_metar(location: Location, force_refresh: bool = False) -> MetarResponse:
    cached = _metar_cache.get(location.id)
    if cached and not force_refresh and time.time() - cached[1] <= METAR_CACHE_TTL_SECONDS:
        return cached[0]

    base = dict(
        location_id=location.id,
        location_name=location.name,
        search_radius_km=METAR_SEARCH_RADIUS_KM,
    )

    try:
        reports = _fetch_metars(_bbox(location.latitude, location.longitude, METAR_SEARCH_RADIUS_KM))
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("METAR fetch failed for %s: %s", location.name, e)
        if cached:
            return cached[0]
        return MetarResponse(**base, message="Aviation Weather Center unreachable.")

    # AWC may return several reports per station (hours=3); keep the newest per station
    latest: Dict[str, Dict[str, Any]] = {}
    for r in reports:
        sid = r.get("icaoId")
        if not sid or r.get("lat") is None or r.get("lon") is None:
            continue
        if sid not in latest or (r.get("obsTime") or 0) > (latest[sid].get("obsTime") or 0):
            latest[sid] = r

    nearest: Optional[Tuple[float, Dict[str, Any]]] = None
    for r in latest.values():
        d = _haversine_km(location.latitude, location.longitude, r["lat"], r["lon"])
        if d <= METAR_SEARCH_RADIUS_KM and (nearest is None or d < nearest[0]):
            nearest = (d, r)

    if nearest is None:
        result = MetarResponse(
            **base, message=f"No METAR-reporting station within {int(METAR_SEARCH_RADIUS_KM)} km."
        )
    else:
        result = MetarResponse(**base, observation=_to_observation(nearest[1], nearest[0]))

    _metar_cache[location.id] = (result, time.time())
    return result
