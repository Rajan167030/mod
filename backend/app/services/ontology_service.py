"""
Ontology: the scenario seen as linked objects (aircraft, tasks, sites, capabilities) rather than tables.
Powers the object explorer (one profile per object with its links and history) and the link graph.
Everything is derived from the existing tables; nothing here writes.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.all_models import (
    Assignment,
    AuditEvent,
    Disruption,
    Resource,
    ResourceAvailability,
    Scenario,
    ScheduleVersion,
    Task,
    User,
)
from app.models.replay_models import WeatherInject
from app.models.weather_models import Location
from app.services.conflict_service import check_schedule_conflicts
from app.services.weather_impact import exposure, site_hours

OBJECT_TYPES = ("aircraft", "task", "site", "capability")


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _active_version(db: Session, scenario_id: str) -> Optional[ScheduleVersion]:
    return (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )


def _quals(r: Resource) -> List[str]:
    return list((r.metadata_json or {}).get("qualifications", []))


def _needs(t: Task) -> List[str]:
    return [q.requirement_value for q in t.requirements if q.requirement_type == "QUALIFICATION"]


class _Snapshot:
    """Everything about one scenario loaded once, so profiles and the graph stay consistent."""

    def __init__(self, db: Session, scenario_id: str):
        self.scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not self.scenario:
            raise NotFoundError("Scenario", scenario_id)
        self.resources = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == scenario_id)}
        self.tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == scenario_id)}
        self.sites = {loc.id: loc for loc in db.query(Location).filter(Location.scenario_id == scenario_id)}
        self.version = _active_version(db, scenario_id)
        self.plan: Dict[str, Assignment] = (
            {a.task_id: a for a in db.query(Assignment).filter(Assignment.schedule_version_id == self.version.id)}
            if self.version else {}
        )
        self.blocks: Dict[str, List[ResourceAvailability]] = {}
        for a in db.query(ResourceAvailability).filter(ResourceAvailability.resource_id.in_(list(self.resources))):
            if not a.available:
                self.blocks.setdefault(a.resource_id, []).append(a)
        self.check = check_schedule_conflicts(db, self.version.id) if self.version else None
        self.conflict_resources = {c.resource_id for c in (self.check.conflicts if self.check else []) if c.resource_id}
        self.conflict_tasks = {tid for c in (self.check.conflicts if self.check else []) for tid in c.task_ids}
        self.hours = site_hours(db, scenario_id)

    # -- status helpers -------------------------------------------------------
    def task_status(self, t: Task) -> str:
        if t.id in self.conflict_tasks:
            return "CONFLICT"
        a = self.plan.get(t.id)
        if not a:
            return "UNASSIGNED"
        if exposure(_utc(a.start_at), _utc(a.end_at), self.hours.get(t.location_id)) == "CRITICAL":
            return "WEATHER_RISK"
        return "PLANNED"

    def site_status(self, loc: Location) -> str:
        sev = set(self.hours.get(loc.id, {}).values())
        return "CRITICAL" if "CRITICAL" in sev else "WARNING" if "WARNING" in sev else "CLEAR"

    def aircraft_status(self, r: Resource) -> str:
        if r.id in self.conflict_resources:
            return "CONFLICT"
        return r.status


def _key(kind: str, oid: str) -> str:
    return f"{kind}:{oid}"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(db: Session, scenario_id: str, q: str = "", kind: Optional[str] = None) -> List[Dict[str, Any]]:
    s = _Snapshot(db, scenario_id)
    q = q.strip().lower()
    out: List[Dict[str, Any]] = []

    def add(item: Dict[str, Any], *haystack: str) -> None:
        if (not kind or item["type"] == kind) and (not q or any(q in (h or "").lower() for h in haystack)):
            out.append(item)

    for r in s.resources.values():
        add({"type": "aircraft", "id": r.id, "title": r.name, "subtitle": r.resource_type.replace("_", " ").lower(),
             "status": s.aircraft_status(r)}, r.name, r.resource_type, *_quals(r))
    for t in sorted(s.tasks.values(), key=lambda t: t.name):
        site = s.sites.get(t.location_id)
        add({"type": "task", "id": t.id, "title": t.name, "subtitle": f"{t.priority.lower()} · {site.name if site else 'no site'}",
             "status": s.task_status(t)}, t.name, t.priority, site.name if site else "", *_needs(t))
    for loc in s.sites.values():
        add({"type": "site", "id": loc.id, "title": loc.name, "subtitle": loc.location_type.replace("_", " ").lower(),
             "status": s.site_status(loc)}, loc.name, loc.location_type)
    caps = sorted({c for r in s.resources.values() for c in _quals(r)} | {c for t in s.tasks.values() for c in _needs(t)})
    for c in caps:
        holders = sum(c in _quals(r) for r in s.resources.values())
        add({"type": "capability", "id": c, "title": c.replace("_", " ").title(), "subtitle": f"{holders} aircraft hold it",
             "status": "SINGLE_POINT" if holders == 1 else "NONE" if holders == 0 else "OK"}, c)
    return out


# ---------------------------------------------------------------------------
# Object profiles
# ---------------------------------------------------------------------------

def _history(db: Session, entity_ids: List[str], limit: int = 25) -> List[Dict[str, Any]]:
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.entity_id.in_(entity_ids))
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    users = {u.id: u.email for u in db.query(User)}
    return [
        {"at": e.created_at, "what": e.action, "who": users.get(e.actor_id, "system"), "detail": e.metadata_json or {}}
        for e in events
    ]


def _disruptions_mentioning(db: Session, scenario_id: str, *needles: str) -> List[Dict[str, Any]]:
    out = []
    for d in db.query(Disruption).filter(Disruption.scenario_id == scenario_id).order_by(Disruption.created_at.desc()):
        payload = d.payload_json or {}
        text = " ".join(str(v) for v in payload.values())
        if any(n and (n in payload.values() or n in text) for n in needles):
            out.append({"at": d.created_at, "type": d.type, "detail": payload})
    return out


def profile(db: Session, scenario_id: str, kind: str, oid: str) -> Dict[str, Any]:
    if kind not in OBJECT_TYPES:
        raise ValidationError(f"Unknown object type '{kind}'.")
    s = _Snapshot(db, scenario_id)
    if kind == "aircraft":
        return _aircraft_profile(db, s, oid)
    if kind == "task":
        return _task_profile(db, s, oid)
    if kind == "site":
        return _site_profile(db, s, oid)
    return _capability_profile(s, oid)


def _link(kind: str, obj_id: str, title: str, relation: str, detail: str = "", status: str = "") -> Dict[str, Any]:
    return {"type": kind, "id": obj_id, "title": title, "relation": relation, "detail": detail, "status": status}


def _aircraft_profile(db: Session, s: _Snapshot, oid: str) -> Dict[str, Any]:
    r = s.resources.get(oid)
    if not r:
        raise NotFoundError("Aircraft", oid)
    sorties = sorted((a for a in s.plan.values() if a.resource_id == r.id), key=lambda a: a.start_at)
    flown_min = sum((_utc(a.end_at) - _utc(a.start_at)).total_seconds() / 60 for a in sorties)
    links = []
    for a in sorties:
        t = s.tasks.get(a.task_id)
        if t:
            links.append(_link("task", t.id, t.name, "flies", f"{_utc(a.start_at):%d %b %H%MZ}–{_utc(a.end_at):%H%MZ}", s.task_status(t)))
    for c in _quals(r):
        links.append(_link("capability", c, c.replace("_", " ").title(), "holds"))
    eligible_unassigned = [
        t for t in s.tasks.values()
        if t.id not in s.plan and all(q in _quals(r) for q in _needs(t))
    ]
    for t in eligible_unassigned:
        links.append(_link("task", t.id, t.name, "could fly", "currently unassigned", s.task_status(t)))
    return {
        "type": "aircraft",
        "id": r.id,
        "title": r.name,
        "status": s.aircraft_status(r),
        "properties": {
            "Type": r.resource_type.replace("_", " ").lower(),
            "Service status": r.status,
            "Max payload": f"{(r.metadata_json or {}).get('max_payload_kg', '—')} kg",
            "Sorties in active plan": len(sorties),
            "Planned flying": f"{flown_min / 60:.1f} h",
        },
        "links": links,
        "unavailability": [
            {"from": b.start_at, "to": b.end_at} for b in sorted(s.blocks.get(r.id, []), key=lambda b: b.start_at)
        ],
        "conflicts": [c.explanation for c in (s.check.conflicts if s.check else []) if c.resource_id == r.id],
        "disruptions": _disruptions_mentioning(db, s.scenario.id, r.id, r.name),
        "history": _history(db, [r.id]),
    }


def _task_profile(db: Session, s: _Snapshot, oid: str) -> Dict[str, Any]:
    t = s.tasks.get(oid)
    if not t:
        raise NotFoundError("Task", oid)
    a = s.plan.get(t.id)
    site = s.sites.get(t.location_id)
    needs = _needs(t)
    links = []
    if a and a.resource_id in s.resources:
        links.append(_link("aircraft", a.resource_id, s.resources[a.resource_id].name, "flown by",
                           f"{_utc(a.start_at):%d %b %H%MZ}–{_utc(a.end_at):%H%MZ}", s.aircraft_status(s.resources[a.resource_id])))
    if site:
        links.append(_link("site", site.id, site.name, "at site", site.location_type.replace("_", " ").lower(), s.site_status(site)))
    for c in needs:
        links.append(_link("capability", c, c.replace("_", " ").title(), "requires"))
    for r in s.resources.values():
        if all(q in _quals(r) for q in needs) and (not a or r.id != a.resource_id):
            links.append(_link("aircraft", r.id, r.name, "could also fly", r.status.lower(), s.aircraft_status(r)))
    site_hours_ = s.hours.get(t.location_id, {})
    window_limits = sorted(
        f"{h:%H%MZ} {sev.lower()}" for h, sev in site_hours_.items()
        if _utc(t.earliest_start) <= h < _utc(t.latest_finish)
    )
    return {
        "type": "task",
        "id": t.id,
        "title": t.name,
        "status": s.task_status(t),
        "properties": {
            "Priority": t.priority,
            "Duration": f"{t.duration_minutes} min",
            "Window opens": f"{_utc(t.earliest_start):%d %b %H%MZ}",
            "Must finish by": f"{_utc(t.latest_finish):%d %b %H%MZ}",
            "Site": site.name if site else "—",
            "Requires": ", ".join(needs) or "—",
            "Planned": f"{s.resources[a.resource_id].name} at {_utc(a.start_at):%H%MZ}" if a and a.resource_id in s.resources else "not in active plan",
            "Delay vs window": f"{int((_utc(a.start_at) - _utc(t.earliest_start)).total_seconds() // 60)} min" if a else "—",
            "Weather in window": ", ".join(window_limits[:8]) or "no limits forecast",
        },
        "links": links,
        "conflicts": [c.explanation for c in (s.check.conflicts if s.check else []) if t.id in c.task_ids],
        "disruptions": _disruptions_mentioning(db, s.scenario.id, t.id, t.name, t.name.split(" ")[0]),
        "history": _history(db, [t.id]),
    }


def _site_profile(db: Session, s: _Snapshot, oid: str) -> Dict[str, Any]:
    loc = s.sites.get(oid)
    if not loc:
        raise NotFoundError("Site", oid)
    tasks = sorted((t for t in s.tasks.values() if t.location_id == loc.id), key=lambda t: t.earliest_start)
    links = [
        _link("task", t.id, t.name, "hosts", t.priority.lower(), s.task_status(t)) for t in tasks
    ]
    flown_by = {s.plan[t.id].resource_id for t in tasks if t.id in s.plan}
    for rid in flown_by:
        if rid in s.resources:
            links.append(_link("aircraft", rid, s.resources[rid].name, "visited by", "", s.aircraft_status(s.resources[rid])))
    hours = s.hours.get(loc.id, {})
    injects = db.query(WeatherInject).filter(WeatherInject.location_id == loc.id).all()
    return {
        "type": "site",
        "id": loc.id,
        "title": loc.name,
        "status": s.site_status(loc),
        "properties": {
            "Kind": loc.location_type.replace("_", " ").lower(),
            "Position": f"{loc.latitude:.3f}N {loc.longitude:.3f}E",
            "Elevation": f"{(loc.metadata_json or {}).get('elevation_m', '—')} m",
            "Tasks here": len(tasks),
            "Critical hours (forecast)": sum(v == "CRITICAL" for v in hours.values()),
            "Warning hours (forecast)": sum(v == "WARNING" for v in hours.values()),
            "Exercise injects": len(injects),
        },
        "links": links,
        "weather_hours": [{"hour": h, "severity": v} for h, v in sorted(hours.items())],
        "conflicts": [],
        "disruptions": _disruptions_mentioning(db, s.scenario.id, loc.name),
        "history": _history(db, [loc.id]),
        "latitude": loc.latitude,
        "longitude": loc.longitude,
    }


def _capability_profile(s: _Snapshot, cap: str) -> Dict[str, Any]:
    holders = [r for r in s.resources.values() if cap in _quals(r)]
    needing = [t for t in s.tasks.values() if cap in _needs(t)]
    if not holders and not needing:
        raise NotFoundError("Capability", cap)
    links = [_link("aircraft", r.id, r.name, "held by", r.status.lower(), s.aircraft_status(r)) for r in holders]
    links += [_link("task", t.id, t.name, "needed by", t.priority.lower(), s.task_status(t)) for t in needing]
    serviceable = [r for r in holders if r.status not in ("GROUNDED", "UNAVAILABLE")]
    return {
        "type": "capability",
        "id": cap,
        "title": cap.replace("_", " ").title(),
        "status": "SINGLE_POINT" if len(holders) == 1 else "NONE" if not holders else "OK",
        "properties": {
            "Aircraft holding it": len(holders),
            "Serviceable now": len(serviceable),
            "Tasks needing it": len(needing),
            "Critical tasks needing it": sum(t.priority == "CRITICAL" for t in needing),
            "Single point of failure": "yes" if len(holders) == 1 else "no",
        },
        "links": links,
        "conflicts": [],
        "disruptions": [],
        "history": [],
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def graph(db: Session, scenario_id: str, include_capabilities: bool = True) -> Dict[str, Any]:
    s = _Snapshot(db, scenario_id)
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for r in s.resources.values():
        nodes.append({"key": _key("aircraft", r.id), "type": "aircraft", "id": r.id, "label": r.name, "status": s.aircraft_status(r)})
    for t in s.tasks.values():
        code = re.match(r"^[A-Z]{1,5}-\d+", t.name)
        nodes.append({"key": _key("task", t.id), "type": "task", "id": t.id, "label": code.group(0) if code else t.name[:16],
                      "full": t.name, "priority": t.priority, "status": s.task_status(t)})
        if t.location_id in s.sites:
            edges.append({"source": _key("task", t.id), "target": _key("site", t.location_id), "relation": "at site"})
        a = s.plan.get(t.id)
        if a and a.resource_id in s.resources:
            edges.append({"source": _key("aircraft", a.resource_id), "target": _key("task", t.id), "relation": "flies"})
    for loc in s.sites.values():
        nodes.append({"key": _key("site", loc.id), "type": "site", "id": loc.id, "label": loc.name, "status": s.site_status(loc)})

    if include_capabilities:
        caps = sorted({c for r in s.resources.values() for c in _quals(r)} | {c for t in s.tasks.values() for c in _needs(t)})
        for c in caps:
            holders = sum(c in _quals(r) for r in s.resources.values())
            nodes.append({"key": _key("capability", c), "type": "capability", "id": c, "label": c.replace("_", " ").lower(),
                          "status": "SINGLE_POINT" if holders == 1 else "OK"})
        for r in s.resources.values():
            for c in _quals(r):
                edges.append({"source": _key("aircraft", r.id), "target": _key("capability", c), "relation": "holds"})
        for t in s.tasks.values():
            for c in _needs(t):
                edges.append({"source": _key("task", t.id), "target": _key("capability", c), "relation": "requires"})

    return {
        "scenario": s.scenario.name,
        "active_version": s.version.version_number if s.version else None,
        "nodes": nodes,
        "edges": edges,
    }
