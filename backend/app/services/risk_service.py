"""
Predicted disruption risk per sortie.

Each factor is an independent chance that the sortie is disrupted (weather, threats,
crew fatigue, aircraft turnaround, schedule slack, stores reserve). They combine as
1 - prod(1 - p_i), so one big factor dominates and many small ones add up without
passing 100%. Every score comes with the factors behind it, so planners can see why.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.all_models import Resource, ResourceAvailability, Task
from app.services.ops_constraints import (
    capabilities, ceiling_m, distance_to_zone_km, is_active, scenario_layers, site_elevation_m, store_demand, zones_at_site,
)
from app.services.weather_impact import exposure, site_hours

HIGH, MEDIUM = 45, 25
NEAR_ZONE_KM = 20
LOOKAHEAD = timedelta(hours=2)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get(a: Any, key: str):
    return a.get(key) if isinstance(a, dict) else getattr(a, key, None)


def level(score: int) -> str:
    return "HIGH" if score >= HIGH else "MEDIUM" if score >= MEDIUM else "LOW"


def assess_plan(db: Session, scenario_id: str, assignments: Iterable[Any]) -> Dict[str, Any]:
    """Score every sortie in a plan. Assignments may be ORM rows or solver dicts."""
    plan = sorted(list(assignments), key=lambda a: _utc(_get(a, "start_at")))
    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == scenario_id)}
    resources = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == scenario_id)}
    layers = scenario_layers(db, scenario_id)
    crews = {c.id: c for c in layers.crews}
    hours = site_hours(db, scenario_id)
    blackouts: Dict[str, List[datetime]] = {}
    for b in db.query(ResourceAvailability).join(Resource).filter(
        Resource.scenario_id == scenario_id, ResourceAvailability.available.is_(False)
    ):
        blackouts.setdefault(b.resource_id, []).append(_utc(b.start_at))

    held: Dict[str, int] = {}
    for st in layers.stores:
        held[st.store_type] = held.get(st.store_type, 0) + st.quantity
    planned_use: Dict[str, int] = {}
    for a in plan:
        t = tasks.get(_get(a, "task_id"))
        for kind, qty in (store_demand(t) if t else {}).items():
            planned_use[kind] = planned_use.get(kind, 0) + qty

    crew_flown: Dict[str, int] = {}
    crew_last_end: Dict[str, datetime] = {}
    aircraft_sorties: Dict[str, int] = {}
    rows = []

    for a in plan:
        t = tasks.get(_get(a, "task_id"))
        r = resources.get(_get(a, "resource_id"))
        if not t or not r:
            continue
        start, end = _utc(_get(a, "start_at")), _utc(_get(a, "end_at"))
        minutes = int((end - start).total_seconds() // 60)
        site = layers.sites.get(t.location_id) if t.location_id else None
        factors: List[Dict[str, Any]] = []

        def add(kind: str, p: float, detail: str) -> None:
            if p > 0:
                factors.append({"kind": kind, "p": p, "points": round(p * 100), "detail": detail})

        # Weather now and the trend just after landing
        site_wx = hours.get(t.location_id) if t.location_id else None
        wx = exposure(start, end, site_wx)
        if wx == "CRITICAL":
            add("weather", 0.35, f"Critical weather forecast at {site.name} during the sortie")
        elif wx == "WARNING":
            add("weather", 0.15, f"Weather warning at {site.name} during the sortie")
        elif exposure(end, end + LOOKAHEAD, site_wx):
            add("weather", 0.08, f"Weather at {site.name} deteriorates within 2 h of landing")

        # Threats and airspace
        if site:
            inside = {z.id for z in zones_at_site(layers.zones, site)}
            for z in layers.zones:
                if not is_active(z, start, end):
                    continue
                if z.id in inside:
                    if z.effect == "AVOID":
                        add("threat", 0.30 * z.confidence, f"Inside {z.name} ({z.kind}, {z.source or 'unknown'} {int(z.confidence * 100)}%)")
                    elif z.exempt_capability and z.exempt_capability in capabilities(r):
                        add("threat", 0.25 * z.confidence, f"Inside {z.name}, protected by {z.exempt_capability}")
                    else:
                        add("airspace" if z.category == "AIRSPACE" else "threat", 0.6, f"Inside {z.name} while it is active")
                else:
                    d = distance_to_zone_km(z, site.latitude, site.longitude)
                    if d <= NEAR_ZONE_KM and z.category == "THREAT":
                        add("threat", 0.10 * z.confidence, f"{d:.0f} km from {z.name}")

        # Crew fatigue and turnaround
        crew = crews.get(_get(a, "crew_id")) if _get(a, "crew_id") else None
        if crew:
            crew_flown[crew.id] = crew_flown.get(crew.id, 0) + minutes
            ratio = (crew.duty_used_minutes + crew_flown[crew.id]) / max(1, crew.max_duty_minutes)
            if ratio >= 0.85:
                add("crew", 0.15, f"{crew.name} at {ratio:.0%} of duty limit")
            elif ratio >= 0.7:
                add("crew", 0.07, f"{crew.name} at {ratio:.0%} of duty limit")
            last = crew_last_end.get(crew.id)
            if last is not None:
                gap = int((start - last).total_seconds() // 60)
                if gap < crew.min_rest_minutes + 60:
                    add("crew", 0.08, f"Short crew turnaround ({gap} min)")
            crew_last_end[crew.id] = end

        # High-altitude operation: performance margins shrink near the service ceiling
        ceiling, elevation = ceiling_m(r), site_elevation_m(site)
        if ceiling and elevation:
            share = elevation / ceiling
            if share >= 0.8:
                add("aircraft", 0.15, f"{site.name} at {elevation:.0f} m is {share:.0%} of the {r.name} ceiling")
            elif share >= 0.6:
                add("aircraft", 0.06, f"High-altitude site ({elevation:.0f} m, {share:.0%} of ceiling)")

        # Aircraft turnaround and tasking
        aircraft_sorties[r.id] = aircraft_sorties.get(r.id, 0) + 1
        next_block = min((b for b in blackouts.get(r.id, []) if b >= end), default=None)
        if next_block is not None and next_block - end < timedelta(minutes=90):
            add("aircraft", 0.08, f"{r.name} maintenance starts {int((next_block - end).total_seconds() // 60)} min after landing")
        if aircraft_sorties[r.id] >= 4:
            add("aircraft", 0.05, f"{r.name} flying its {aircraft_sorties[r.id]}th sortie")

        # Slack before the deadline: any delay eats it
        slack = int((_utc(t.latest_finish) - end).total_seconds() // 60)
        if slack < 30:
            add("schedule", 0.12, f"Only {slack} min slack to the deadline")
        elif slack < 90:
            add("schedule", 0.05, f"{slack} min slack to the deadline")

        for kind in store_demand(t):
            if planned_use.get(kind, 0) >= held.get(kind, 0):
                add("stores", 0.05, f"No reserve {kind.replace('_', ' ').lower()} left after this plan")

        score = round(100 * (1 - math.prod(1 - f["p"] for f in factors)))
        factors.sort(key=lambda f: -f["p"])
        rows.append({
            "task_id": t.id, "task_name": t.name, "priority": t.priority,
            "resource_id": r.id, "resource_name": r.name,
            "crew_id": crew.id if crew else None, "crew_name": crew.name if crew else None,
            "site": site.name if site else None,
            "start_at": start, "end_at": end,
            "score": score, "level": level(score),
            "factors": [{k: v for k, v in f.items() if k != "p"} for f in factors],
        })

    rows.sort(key=lambda x: -x["score"])
    scores = [x["score"] for x in rows]
    drivers: Dict[str, int] = {}
    for x in rows:
        for f in x["factors"]:
            drivers[f["kind"]] = drivers.get(f["kind"], 0) + 1
    return {
        "sorties": rows,
        "summary": {
            "sorties": len(rows),
            "average": round(sum(scores) / len(scores)) if scores else 0,
            "max": max(scores, default=0),
            "high": sum(s >= HIGH for s in scores),
            "medium": sum(MEDIUM <= s < HIGH for s in scores),
            "low": sum(s < MEDIUM for s in scores),
            "critical_high": sum(x["level"] == "HIGH" and x["priority"] == "CRITICAL" for x in rows),
            "drivers": dict(sorted(drivers.items(), key=lambda kv: -kv[1])),
        },
    }
