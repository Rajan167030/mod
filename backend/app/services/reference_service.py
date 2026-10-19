"""
Reference data for the theatre map: every Indian airfield (OurAirports), the AIP prohibited, restricted
and danger areas (AAI eAIP ENR 5.1), published aircraft type specifications, and live METARs.
Static files come from the data pack (settings.REFERENCE_DATA_DIR); METARs are fetched from NOAA AWC
and cached, falling back to the pack's snapshot when the service cannot be reached.
"""
import csv
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.errors import NotFoundError
from app.services.metar_service import AWC_METAR_URL

logger = logging.getLogger(__name__)

METAR_TTL_SECONDS = 600
METAR_BATCH = 40
_metar_cache: Dict[str, Any] = {}
_metar_lock = threading.Lock()


def _file(name: str) -> Path:
    path = Path(settings.REFERENCE_DATA_DIR) / name
    if not path.exists():
        raise NotFoundError("Reference data file", name)
    return path


def _rows(name: str) -> List[Dict[str, str]]:
    with open(_file(name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


@lru_cache(maxsize=1)
def airfields() -> List[Dict[str, Any]]:
    return [{
        "ident": r["ident"], "icao": r["icao"] or None, "iata": r["iata"] or None, "type": r["type"], "name": r["name"],
        "latitude": float(r["latitude"]), "longitude": float(r["longitude"]), "elevation_m": _num(r["elevation_m"]),
        "state": r["state"], "municipality": r["municipality"] or None,
    } for r in _rows("airfields_india_ourairports.csv")]


@lru_cache(maxsize=1)
def airspace() -> List[Dict[str, Any]]:
    out = []
    for r in _rows("airspace_enr51_india.csv"):
        polygon = [[float(x) for x in p.split()] for p in r["polygon"].split(";") if p.strip()] if r["polygon"] else None
        out.append({
            "designator": r["designator"], "type": r["type"], "fir": r["fir"], "name": r["name"].strip("[] "),
            "geometry": r["geometry"], "polygon": polygon,
            "center": [float(r["center_lat"]), float(r["center_lon"])] if r["center_lat"] else None,
            "radius_km": _num(r["radius_km"]), "vertical_limits": r["vertical_limits"], "remarks": r["remarks"],
            "approximated_arcs": r["has_arcs"] == "yes",
        })
    return out


@lru_cache(maxsize=1)
def aircraft_types() -> List[Dict[str, Any]]:
    out = []
    for r in _rows("aircraft_types_wikipedia.csv"):
        out.append({**{k: r[k] for k in ("type_name", "airops_type", "role", "crew", "capacity", "source_url")},
                    **{k: _num(r[k]) for k in ("max_takeoff_weight_kg", "max_speed_kmh", "cruise_speed_kmh",
                                               "range_km", "ferry_range_km", "service_ceiling_m")}})
    return out


def _snapshot() -> List[Dict[str, Any]]:
    try:
        return _rows("metar_taf_india_snapshot.csv")
    except NotFoundError:
        return []


def _shape(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "icao": r.get("icaoId"), "name": r.get("name"), "latitude": _num(str(r.get("lat") or "")),
        "longitude": _num(str(r.get("lon") or "")), "flight_category": r.get("fltCat") or None,
        "raw_metar": r.get("rawOb"), "raw_taf": r.get("rawTaf") or None,
        "temperature_c": _num(str(r.get("temp") if r.get("temp") is not None else "")),
        "wind_dir": r.get("wdir"), "wind_kt": _num(str(r.get("wspd") if r.get("wspd") is not None else "")),
        "visibility": r.get("visib"), "report_time": r.get("reportTime"),
    }


def metars() -> Dict[str, Any]:
    """Current METARs for Indian stations: live when possible, else the pack snapshot."""
    with _metar_lock:
        cached = _metar_cache.get("data")
        if cached and time.time() - cached["fetched"] < METAR_TTL_SECONDS:
            return cached["body"]
        codes = sorted({a["icao"] for a in airfields() if a["icao"] and len(a["icao"]) == 4 and a["icao"].startswith("V")})
        live: List[Dict[str, Any]] = []
        try:
            with httpx.Client(timeout=15, headers={"User-Agent": "airops-sih-prototype/1.0"}) as client:
                for i in range(0, len(codes), METAR_BATCH):
                    r = client.get(AWC_METAR_URL, params={"ids": ",".join(codes[i:i + METAR_BATCH]), "format": "json", "taf": "true"})
                    r.raise_for_status()
                    if r.text.strip():
                        live.extend(r.json())
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Live METAR fetch for the theatre map failed: %s", e)
            live = []
        if live:
            body = {"source": "live", "provider": "NOAA Aviation Weather Center", "stations": [_shape(r) for r in live]}
        else:
            body = {"source": "snapshot", "provider": "NOAA Aviation Weather Center (saved snapshot)",
                    "stations": [_shape(r) for r in _snapshot()]}
        body["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Cache failures briefly so a dead network is not retried on every map load
        _metar_cache["data"] = {"body": body, "fetched": time.time() if live else time.time() - METAR_TTL_SECONDS + 60}
        return body
