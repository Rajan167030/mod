"""
Weather Constraint Service — Converts weather alerts into scheduling constraints.
Weather alerts are mapped to explicit constraints for the OR-Tools scheduler.
The weather provider never directly modifies or auto-approves a schedule.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.models.all_models import Resource, Task, Scenario
from app.models.weather_models import Location
from app.schemas.weather_schemas import (
    WeatherAlertItem,
    WeatherConstraint,
    WeatherConstraintsResponse,
    WeatherThresholdConfig,
)
from app.services.weather_rules_service import get_alerts_for_scenario, get_default_thresholds

logger = logging.getLogger(__name__)


def _find_affected_resources(
    db: Session,
    scenario_id: str,
    location: Location,
) -> List[str]:
    """
    Find resources in the scenario that could be affected by weather at this location.
    Uses proximity or metadata association (for this prototype, all resources
    in the scenario are considered potentially affected by a CRITICAL alert
    since we have a small synthetic dataset).
    """
    resources = db.query(Resource).filter_by(scenario_id=scenario_id).all()
    return [r.id for r in resources if r.status != "UNAVAILABLE"]


def _find_affected_tasks(
    db: Session,
    scenario_id: str,
    alert: WeatherAlertItem,
) -> List[str]:
    """
    Find tasks that fall within the alert's forecast window.
    For this prototype, checks tasks whose scheduling windows overlap
    with the alert forecast timestamp ± 2 hours.
    """
    window_start = alert.forecast_timestamp - timedelta(hours=2)
    window_end = alert.forecast_timestamp + timedelta(hours=2)

    tasks = db.query(Task).filter(
        Task.scenario_id == scenario_id,
        Task.earliest_start <= window_end,
        Task.latest_finish >= window_start,
    ).all()

    return [t.id for t in tasks]


def generate_weather_constraints(
    db: Session,
    scenario_id: str,
    thresholds: Optional[WeatherThresholdConfig] = None,
) -> WeatherConstraintsResponse:
    """
    Convert validated weather alerts into scheduling constraints.

    Constraint mapping:
    - CRITICAL alerts → HARD_BLACKOUT (resource unavailable) or REVIEW_FLAG
    - WARNING alerts → SOFT_PENALTY (increased cost for affected assignments)
    - INFO alerts → no constraint, informational only

    Stale/unknown data → conservative fallback: treat as WARNING + require human review.
    """
    if thresholds is None:
        thresholds = get_default_thresholds()

    # Get alerts for the scenario
    alerts_response = get_alerts_for_scenario(db, scenario_id, thresholds)
    locations = {
        loc.id: loc
        for loc in db.query(Location).filter_by(scenario_id=scenario_id).all()
    }

    constraints: List[WeatherConstraint] = []

    for alert in alerts_response.alerts:
        location = locations.get(alert.location_id)
        if not location:
            continue

        # Validate that the alert belongs to this scenario
        if location.scenario_id != scenario_id:
            logger.warning(
                "Alert location %s does not belong to scenario %s — skipping",
                alert.location_id, scenario_id
            )
            continue

        affected_task_ids = _find_affected_tasks(db, scenario_id, alert)

        if alert.severity == "CRITICAL":
            if alert.variable == "wind_speed":
                # Critical wind: hard blackout for resources
                affected_resource_ids = _find_affected_resources(db, scenario_id, location)
                constraints.append(WeatherConstraint(
                    alert=alert,
                    constraint_type="HARD_BLACKOUT",
                    affected_resource_ids=affected_resource_ids,
                    affected_task_ids=affected_task_ids,
                    explanation=(
                        f"CRITICAL wind speed ({alert.observed_value} km/h) at '{alert.location_name}' — "
                        f"resources should be marked unavailable during forecast window. "
                        f"Hard constraint — will prevent scheduling during this period."
                    ),
                ))
            else:
                # Critical precipitation/temperature: review flag
                constraints.append(WeatherConstraint(
                    alert=alert,
                    constraint_type="REVIEW_FLAG",
                    affected_task_ids=affected_task_ids,
                    explanation=(
                        f"CRITICAL {alert.variable} ({alert.observed_value}) at '{alert.location_name}' — "
                        f"affected tasks flagged for human review before scheduling."
                    ),
                ))

        elif alert.severity == "WARNING":
            constraints.append(WeatherConstraint(
                alert=alert,
                constraint_type="SOFT_PENALTY",
                affected_task_ids=affected_task_ids,
                penalty_weight=500,  # Additional penalty in objective function
                explanation=(
                    f"WARNING {alert.variable} ({alert.observed_value}) at '{alert.location_name}' — "
                    f"soft penalty applied to discourage scheduling during this period."
                ),
            ))

    # Handle stale/unknown freshness with conservative fallback
    if alerts_response.freshness_summary in ("STALE", "UNKNOWN"):
        for constraint in constraints:
            if constraint.constraint_type == "SOFT_PENALTY":
                constraint.constraint_type = "REVIEW_FLAG"
                constraint.explanation += (
                    " [CONSERVATIVE FALLBACK: Weather data is "
                    f"{alerts_response.freshness_summary.lower()} — "
                    f"elevated to review flag. Human assessment required.]"
                )

    hard = sum(1 for c in constraints if c.constraint_type == "HARD_BLACKOUT")
    soft = sum(1 for c in constraints if c.constraint_type == "SOFT_PENALTY")
    review = sum(1 for c in constraints if c.constraint_type == "REVIEW_FLAG")

    return WeatherConstraintsResponse(
        scenario_id=scenario_id,
        constraints=constraints,
        total_constraints=len(constraints),
        hard_constraints=hard,
        soft_constraints=soft,
        review_flags=review,
        weather_data_available=len(alerts_response.alerts) > 0 or alerts_response.freshness_summary == "FRESH",
        freshness_summary=alerts_response.freshness_summary,
    )


def get_weather_blackout_windows(
    constraints: WeatherConstraintsResponse,
) -> List[Dict[str, Any]]:
    """
    Extract blackout windows from weather constraints for the solver.
    Returns a list of dicts: {resource_id, start_at, end_at} for hard constraints.
    """
    blackouts = []
    for constraint in constraints.constraints:
        if constraint.constraint_type == "HARD_BLACKOUT":
            alert = constraint.alert
            # Create a 4-hour blackout window centered on the forecast timestamp
            start = alert.forecast_timestamp - timedelta(hours=2)
            end = alert.forecast_timestamp + timedelta(hours=2)
            for rid in constraint.affected_resource_ids:
                blackouts.append({
                    "resource_id": rid,
                    "start_at": start,
                    "end_at": end,
                    "reason": f"Weather: {constraint.explanation}",
                })
    return blackouts


def get_weather_penalty_tasks(
    constraints: WeatherConstraintsResponse,
) -> Dict[str, int]:
    """
    Extract task penalty adjustments from weather constraints for the solver.
    Returns a dict: {task_id: additional_penalty_weight}.
    """
    penalties: Dict[str, int] = {}
    for constraint in constraints.constraints:
        if constraint.constraint_type == "SOFT_PENALTY" and constraint.penalty_weight:
            for tid in constraint.affected_task_ids:
                penalties[tid] = penalties.get(tid, 0) + constraint.penalty_weight
    return penalties
