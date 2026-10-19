"""
What the force has and how much of it the active plan uses: flying hours available and planned per
aircraft and per type, spare hours, the next free slot, aircraft free hour by hour, crew duty left,
and stores left after the plan.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.all_models import Resource, ResourceAvailability, Scenario, Task
from app.services.ops_constraints import scenario_layers, store_demand
from app.services.planning_service import active_version, plan_rows

HOUR = timedelta(hours=1)
Interval = Tuple[datetime, datetime]


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clip(iv: Interval, lo: datetime, hi: datetime) -> Optional[Interval]:
    s, e = max(iv[0], lo), min(iv[1], hi)
    return (s, e) if s < e else None


def _hours(ivs: List[Interval]) -> float:
    """Total length of possibly overlapping intervals, in hours."""
    total, cur = 0.0, None
    for s, e in sorted(ivs):
        if cur and s <= cur[1]:
            cur = (cur[0], max(cur[1], e))
        else:
            if cur:
                total += (cur[1] - cur[0]).total_seconds()
            cur = (s, e)
    if cur:
        total += (cur[1] - cur[0]).total_seconds()
    return total / 3600


def _next_free(after: datetime, hi: datetime, taken: List[Interval], minimum: timedelta = HOUR) -> Optional[datetime]:
    """Start of the first gap of at least `minimum` after `after`."""
    t = after
    for s, e in sorted(taken):
        if e <= t:
            continue
        if s - t >= minimum:
            return t
        t = max(t, e)
    return t if hi - t >= minimum else None


def capacity(db: Session, scenario_id: str) -> Dict[str, Any]:
    if not db.query(Scenario).filter(Scenario.id == scenario_id).first():
        raise NotFoundError("Scenario", scenario_id)
    tasks = db.query(Task).filter(Task.scenario_id == scenario_id).all()
    version = active_version(db, scenario_id)
    plan = plan_rows(db, version)
    resources = db.query(Resource).filter(Resource.scenario_id == scenario_id).order_by(Resource.resource_type, Resource.name).all()
    if not tasks:
        return {"horizon": None, "aircraft": [], "types": [], "hourly": [], "crews": None, "stores": [], "plan_version": None}

    h0 = min(_utc(t.earliest_start) for t in tasks).replace(minute=0, second=0, microsecond=0)
    h1 = max(_utc(t.latest_finish) for t in tasks)
    if h1.minute or h1.second:
        h1 = h1.replace(minute=0, second=0, microsecond=0) + HOUR
    horizon_h = (h1 - h0).total_seconds() / 3600
    now = datetime.now(timezone.utc)
    look_from = min(max(now, h0), h1)

    blackouts: Dict[str, List[Interval]] = {}
    for b in db.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == scenario_id, ResourceAvailability.available.is_(False)):
        iv = _clip((_utc(b.start_at), _utc(b.end_at)), h0, h1)
        if iv:
            blackouts.setdefault(b.resource_id, []).append(iv)
    sorties: Dict[str, List[Interval]] = {}
    for a in plan:
        iv = _clip((_utc(a.start_at), _utc(a.end_at)), h0, h1)
        if iv:
            sorties.setdefault(a.resource_id, []).append(iv)

    aircraft = []
    for r in resources:
        grounded = r.status in ("GROUNDED", "UNAVAILABLE")
        down = [(h0, h1)] if grounded else blackouts.get(r.id, [])
        available = max(0.0, horizon_h - _hours(down))
        planned = _hours(sorties.get(r.id, []))
        nxt = None if grounded else _next_free(look_from, h1, down + sorties.get(r.id, []))
        aircraft.append({
            "id": r.id, "name": r.name, "type": r.resource_type, "model": (r.metadata_json or {}).get("model"),
            "status": r.status, "qualifications": (r.metadata_json or {}).get("qualifications", []),
            "available_hours": round(available, 1), "planned_hours": round(planned, 1),
            "spare_hours": round(max(0.0, available - planned), 1),
            "utilisation": round(planned / available, 2) if available else None,
            "sorties": len(sorties.get(r.id, [])), "maintenance_hours": round(_hours(blackouts.get(r.id, [])), 1),
            "next_free_at": nxt,
        })

    types: Dict[str, Dict[str, Any]] = {}
    for a in aircraft:
        t = types.setdefault(a["type"], {"type": a["type"], "aircraft": 0, "serviceable": 0, "available_hours": 0.0, "planned_hours": 0.0, "free_now": 0})
        t["aircraft"] += 1
        t["serviceable"] += a["status"] not in ("GROUNDED", "UNAVAILABLE")
        t["available_hours"] += a["available_hours"]
        t["planned_hours"] += a["planned_hours"]
    for t in types.values():
        t["available_hours"] = round(t["available_hours"], 1)
        t["planned_hours"] = round(t["planned_hours"], 1)
        t["spare_hours"] = round(max(0.0, t["available_hours"] - t["planned_hours"]), 1)
        t["utilisation"] = round(t["planned_hours"] / t["available_hours"], 2) if t["available_hours"] else None

    # Aircraft free at each hour (not grounded, not in maintenance, not flying)
    hourly = []
    h = h0
    while h < h1:
        free_by_type: Dict[str, int] = {}
        for r in resources:
            if r.status in ("GROUNDED", "UNAVAILABLE"):
                continue
            taken = blackouts.get(r.id, []) + sorties.get(r.id, [])
            if not any(s < h + HOUR and h < e for s, e in taken):
                free_by_type[r.resource_type] = free_by_type.get(r.resource_type, 0) + 1
        hourly.append({"hour": h, "free": sum(free_by_type.values()), "by_type": free_by_type})
        h += HOUR
    for t in types.values():
        t["free_now"] = next((x["by_type"].get(t["type"], 0) for x in hourly if x["hour"] <= look_from < x["hour"] + HOUR), 0)

    layers = scenario_layers(db, scenario_id)
    crews = None
    if layers.crews:
        flown: Dict[str, int] = {}
        for a in plan:
            if a.crew_id:
                flown[a.crew_id] = flown.get(a.crew_id, 0) + int((_utc(a.end_at) - _utc(a.start_at)).total_seconds() // 60)
        ready = [c for c in layers.crews if c.status == "AVAILABLE"]
        crews = {
            "total": len(layers.crews), "available": len(ready),
            "duty_left_hours": round(sum(max(0, c.max_duty_minutes - c.duty_used_minutes - flown.get(c.id, 0)) for c in ready) / 60, 1),
            "near_limit": sum((c.duty_used_minutes + flown.get(c.id, 0)) / max(1, c.max_duty_minutes) >= 0.85 for c in ready),
        }

    by_task = {t.id: t for t in tasks}
    used: Dict[str, int] = {}
    for a in plan:
        for kind, qty in (store_demand(by_task[a.task_id]) if a.task_id in by_task else {}).items():
            used[kind] = used.get(kind, 0) + qty
    stores = [{"store_type": s.store_type, "name": s.name, "held": s.quantity, "planned": used.get(s.store_type, 0),
               "left": s.quantity - used.get(s.store_type, 0), "unit": s.unit} for s in layers.stores]

    total_avail = sum(a["available_hours"] for a in aircraft)
    total_plan = sum(a["planned_hours"] for a in aircraft)
    return {
        "plan_version": version.version_number if version else None,
        "horizon": {"start": h0, "end": h1, "hours": round(horizon_h, 1)},
        "summary": {
            "aircraft": len(aircraft), "serviceable": sum(a["status"] not in ("GROUNDED", "UNAVAILABLE") for a in aircraft),
            "available_hours": round(total_avail, 1), "planned_hours": round(total_plan, 1),
            "spare_hours": round(max(0.0, total_avail - total_plan), 1),
            "utilisation": round(total_plan / total_avail, 2) if total_avail else None,
            "tasks": len(tasks), "tasks_planned": len({a.task_id for a in plan}),
        },
        "aircraft": aircraft,
        "types": sorted(types.values(), key=lambda t: -(t["utilisation"] or 0)),
        "hourly": hourly,
        "crews": crews,
        "stores": stores,
    }
