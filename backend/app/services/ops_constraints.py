"""
Turns threats, airspace, crews and stores into solver inputs.

Zones work like weather: a task is affected when its site lies inside an active zone.
  - BLOCK without an exemption  -> hard window for the task (nobody may fly it then)
  - BLOCK with an exemption     -> hard window only for aircraft that lack the capability
  - AVOID                       -> soft window the solver avoids when it can
Crews and stores are passed through as plain specs so the solver never touches the session.
"""
import math
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.ops_models import Crew, OpsZone, StoreItem
from app.models.weather_models import Location

Window = Tuple[datetime, datetime]
EARTH_KM = 6371.0


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def _inside_polygon(lat: float, lon: float, poly: List[List[float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _segment_km(lat: float, lon: float, a: List[float], b: List[float]) -> float:
    """Distance from a point to a polygon edge, on a local flat projection (fine at these scales)."""
    kx = 111.32 * math.cos(math.radians(lat))
    ax, ay = (a[1] - lon) * kx, (a[0] - lat) * 110.57
    bx, by = (b[1] - lon) * kx, (b[0] - lat) * 110.57
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1e-12)))
    return math.hypot(ax + t * dx, ay + t * dy)


def distance_to_zone_km(zone: Any, lat: float, lon: float) -> float:
    """0 inside the zone, otherwise the distance to its edge."""
    poly = zone.polygon_json
    if poly and len(poly) >= 3:
        if _inside_polygon(lat, lon, poly):
            return 0.0
        return min(_segment_km(lat, lon, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))
    if zone.center_lat is None or zone.center_lon is None or not zone.radius_km:
        return math.inf
    return max(0.0, haversine_km(lat, lon, zone.center_lat, zone.center_lon) - zone.radius_km)


def zone_contains(zone: Any, lat: float, lon: float) -> bool:
    return distance_to_zone_km(zone, lat, lon) == 0.0


def active_window(zone: Any, lo: datetime, hi: datetime) -> Optional[Window]:
    """The part of [lo, hi) during which the zone is active, or None."""
    start = max(_utc(lo), _utc(zone.active_from)) if zone.active_from else _utc(lo)
    end = min(_utc(hi), _utc(zone.active_until)) if zone.active_until else _utc(hi)
    return (start, end) if start < end else None


def is_active(zone: Any, start: datetime, end: datetime) -> bool:
    return active_window(zone, start, end) is not None


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

def store_demand(task: Any) -> Dict[str, int]:
    """STORE requirements are written as 'TYPE' or 'TYPE:quantity'."""
    out: Dict[str, int] = {}
    for req in task.requirements:
        if req.requirement_type != "STORE":
            continue
        kind, _, qty = req.requirement_value.partition(":")
        out[kind.strip().upper()] = out.get(kind.strip().upper(), 0) + (int(qty) if qty.strip().isdigit() else 1)
    return out


def capabilities(resource: Any) -> set:
    return set((resource.metadata_json or {}).get("qualifications", []))


def carries(resource: Any, store_type: str) -> bool:
    return store_type in set((resource.metadata_json or {}).get("store_types", []))


def crew_can_fly(crew: Any, resource_type: str) -> bool:
    types = crew.aircraft_types or []
    return not types or resource_type in types


def ceiling_m(resource: Any) -> Optional[float]:
    v = (resource.metadata_json or {}).get("service_ceiling_m")
    return float(v) if v else None


def site_elevation_m(site: Any) -> Optional[float]:
    v = (site.metadata_json or {}).get("elevation_m") if site is not None else None
    return float(v) if v not in (None, "") else None


def above_ceiling(resource: Any, site: Any) -> bool:
    """True when the site is higher than the aircraft can operate (published service ceiling)."""
    c, e = ceiling_m(resource), site_elevation_m(site)
    return c is not None and e is not None and e > c


def crew_spec(c: Crew) -> SimpleNamespace:
    return SimpleNamespace(
        id=c.id, name=c.name, aircraft_types=list(c.aircraft_types or []), status=c.status,
        max_duty_minutes=c.max_duty_minutes, min_rest_minutes=c.min_rest_minutes,
        duty_used_minutes=c.duty_used_minutes,
        duty_start=_utc(c.duty_start) if c.duty_start else None,
        duty_end=_utc(c.duty_end) if c.duty_end else None,
    )


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

def scenario_layers(db: Session, scenario_id: str) -> SimpleNamespace:
    """Everything the constraint and risk models need, detached from the session."""
    return SimpleNamespace(
        zones=db.query(OpsZone).filter(OpsZone.scenario_id == scenario_id).all(),
        crews=[crew_spec(c) for c in db.query(Crew).filter(Crew.scenario_id == scenario_id).order_by(Crew.name)],
        stores=db.query(StoreItem).filter(StoreItem.scenario_id == scenario_id).all(),
        sites={loc.id: loc for loc in db.query(Location).filter(Location.scenario_id == scenario_id)},
    )


def zones_at_site(zones: Iterable[Any], site: Any) -> List[Any]:
    if site is None:
        return []
    return [z for z in zones if zone_contains(z, site.latitude, site.longitude)]


def affected_task_ids(zone: Any, tasks: Iterable[Any], sites: Dict[str, Any]) -> List[str]:
    out = []
    for t in tasks:
        site = sites.get(t.location_id) if t.location_id else None
        if site and zone_contains(zone, site.latitude, site.longitude) and active_window(zone, t.earliest_start, t.latest_finish):
            out.append(t.id)
    return out


def merge_windows(*maps: Optional[Dict[Any, List[Window]]]) -> Dict[Any, List[Window]]:
    out: Dict[Any, List[Window]] = {}
    for m in maps:
        for k, v in (m or {}).items():
            out.setdefault(k, []).extend(v)
    return out


def solver_ops_kwargs(db: Session, scenario_id: str, tasks: List[Any], resources: List[Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Solver keyword arguments for zones, crews and stores, plus a summary for the run's metrics."""
    layers = scenario_layers(db, scenario_id)
    hard: Dict[str, List[Window]] = {}
    soft: Dict[str, List[Window]] = {}
    pair_hard: Dict[Tuple[str, str], List[Window]] = {}
    forbidden = set()

    for t in tasks:
        site = layers.sites.get(t.location_id) if t.location_id else None
        forbidden |= {(t.id, r.id) for r in resources if above_ceiling(r, site)}
        for z in zones_at_site(layers.zones, site):
            w = active_window(z, t.earliest_start, t.latest_finish)
            if not w:
                continue
            if z.effect == "AVOID":
                soft.setdefault(t.id, []).append(w)
            elif z.exempt_capability:
                for r in resources:
                    if z.exempt_capability not in capabilities(r):
                        pair_hard.setdefault((t.id, r.id), []).append(w)
            else:
                hard.setdefault(t.id, []).append(w)

    demand_types = {k for t in tasks for k in store_demand(t)}
    stock = None
    if layers.stores or demand_types:
        stock = {k: 0 for k in demand_types}
        for s in layers.stores:
            stock[s.store_type] = stock.get(s.store_type, 0) + s.quantity

    crews = None
    if layers.crews:
        crews = [c for c in layers.crews if c.status == "AVAILABLE"]

    kwargs = {
        "task_hard_windows": hard,
        "task_soft_windows": soft,
        "pair_hard_windows": pair_hard,
        "crews": crews,
        "store_stock": stock,
        "forbidden_pairs": forbidden,
    }
    info = {
        "zones": len(layers.zones),
        "tasks_blocked_by_zones": len(hard),
        "tasks_restricted_to_protected_aircraft": len({t for t, _ in pair_hard}),
        "tasks_avoiding_zones": len(soft),
        "crews_available": len(crews) if crews is not None else None,
        "crews_total": len(layers.crews),
        "store_types": len(stock) if stock is not None else 0,
        "pairs_above_ceiling": len(forbidden),
    }
    return kwargs, info


def combine_with_weather(weather_kwargs: Dict[str, Any], ops_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Merge zone windows into the weather windows (both use task_hard/soft_windows)."""
    out = dict(weather_kwargs)
    out.update({k: v for k, v in ops_kwargs.items() if k not in ("task_hard_windows", "task_soft_windows")})
    out["task_hard_windows"] = merge_windows(weather_kwargs.get("task_hard_windows"), ops_kwargs.get("task_hard_windows"))
    out["task_soft_windows"] = merge_windows(weather_kwargs.get("task_soft_windows"), ops_kwargs.get("task_soft_windows"))
    return out
