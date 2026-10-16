"""
Per-site weather impact on tasks.

Each task flown at a site is affected only by that site's forecast:
  - CRITICAL hours become hard windows the task may not overlap
  - WARNING hours become soft windows the solver avoids when it can
Tasks without a site are not weather-constrained by this model.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.all_models import Task
from app.services.weather_rules_service import get_alerts_for_scenario

HOUR = timedelta(hours=1)
SEVERITY_RANK = {"WARNING": 1, "CRITICAL": 2}

HoursBySite = Dict[str, Dict[datetime, str]]
Window = Tuple[datetime, datetime]


def _floor_hour(dt: datetime) -> datetime:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def site_hours(db: Session, scenario_id: str) -> HoursBySite:
    """Worst severity per (site, forecast hour) from the scenario's weather alerts."""
    out: HoursBySite = {}
    for a in get_alerts_for_scenario(db, scenario_id).alerts:
        if a.severity not in SEVERITY_RANK or a.variable == "all":
            continue
        h = _floor_hour(a.forecast_timestamp)
        site = out.setdefault(a.location_id, {})
        if SEVERITY_RANK[a.severity] > SEVERITY_RANK.get(site.get(h, ""), 0):
            site[h] = a.severity
    return out


def merge_hours(hours: Iterable[datetime]) -> List[Window]:
    """Turn a set of hour starts into contiguous [start, end) windows."""
    windows: List[Window] = []
    for h in sorted(hours):
        if windows and windows[-1][1] == h:
            windows[-1] = (windows[-1][0], h + HOUR)
        else:
            windows.append((h, h + HOUR))
    return windows


def task_weather_windows(tasks: List[Task], hours: HoursBySite) -> Tuple[Dict[str, List[Window]], Dict[str, List[Window]]]:
    """(hard, soft) windows per task id, limited to each task's own planning window."""
    hard: Dict[str, List[Window]] = {}
    soft: Dict[str, List[Window]] = {}
    for t in tasks:
        site = hours.get(t.location_id) if t.location_id else None
        if not site:
            continue
        lo, hi = _floor_hour(t.earliest_start), t.latest_finish if t.latest_finish.tzinfo else t.latest_finish.replace(tzinfo=timezone.utc)
        relevant = {h: s for h, s in site.items() if lo <= h < hi}
        crit = merge_hours(h for h, s in relevant.items() if s == "CRITICAL")
        warn = merge_hours(h for h, s in relevant.items() if s == "WARNING")
        if crit:
            hard[t.id] = crit
        if warn:
            soft[t.id] = warn
    return hard, soft


def exposure(start: datetime, end: datetime, site: Optional[Dict[datetime, str]]) -> Optional[str]:
    """Worst severity an interval overlaps at one site, or None."""
    if not site:
        return None
    worst = None
    h = _floor_hour(start)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    while h < end:
        sev = site.get(h)
        if sev == "CRITICAL":
            return sev
        if sev == "WARNING":
            worst = sev
        h += HOUR
    return worst


def uses_site_model(tasks: List[Task]) -> bool:
    return any(t.location_id for t in tasks)


def solver_weather_kwargs(db: Session, scenario_id: str, tasks: List[Task]) -> Tuple[dict, dict]:
    """
    Solver keyword arguments for weather, plus a summary for the run's metrics.
    Scenarios whose tasks have sites use the per-site model; older scenarios keep the
    scenario-wide model (critical wind blacks out every resource).
    """
    alerts = get_alerts_for_scenario(db, scenario_id)
    if uses_site_model(tasks):
        hard, soft = task_weather_windows(tasks, site_hours(db, scenario_id))
        info = {
            "applied": True,
            "model": "per_site",
            "total_constraints": sum(map(len, hard.values())) + sum(map(len, soft.values())),
            "hard_blackouts": sum(map(len, hard.values())),
            "soft_penalties": sum(map(len, soft.values())),
            "tasks_affected": len(set(hard) | set(soft)),
            "freshness": alerts.freshness_summary,
        }
        return {"task_hard_windows": hard, "task_soft_windows": soft}, info

    from app.services.weather_constraint_service import (
        generate_weather_constraints,
        get_weather_blackout_windows,
        get_weather_penalty_tasks,
    )
    constraints = generate_weather_constraints(db, scenario_id)
    info = {
        "applied": True,
        "model": "scenario_wide",
        "total_constraints": constraints.total_constraints,
        "hard_blackouts": constraints.hard_constraints,
        "soft_penalties": constraints.soft_constraints,
        "review_flags": constraints.review_flags,
        "freshness": constraints.freshness_summary,
    }
    return {
        "weather_blackouts": get_weather_blackout_windows(constraints),
        "weather_penalties": get_weather_penalty_tasks(constraints),
    }, info
