"""
Unit tests for Weather Constraint Service.
Tests mapping alerts to constraints, blackout windows, and soft penalties.
"""
from datetime import datetime, timezone, timedelta
from app.schemas.weather_schemas import WeatherAlertItem, WeatherConstraintsResponse, WeatherConstraint
from app.services.weather_constraint_service import (
    get_weather_blackout_windows,
    get_weather_penalty_tasks,
)


def test_blackout_windows_extraction():
    forecast_time = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    alert = WeatherAlertItem(
        location_id="loc-1",
        location_name="Base North",
        forecast_timestamp=forecast_time,
        source_timestamp=forecast_time,
        variable="wind_speed",
        observed_value=72.0,
        threshold=65.0,
        severity="CRITICAL",
        freshness="FRESH",
        explanation="High wind alert",
    )
    constraint = WeatherConstraint(
        alert=alert,
        constraint_type="HARD_BLACKOUT",
        affected_resource_ids=["res-1", "res-2"],
        explanation="Hard blackout for wind",
    )
    response = WeatherConstraintsResponse(
        scenario_id="scen-1",
        constraints=[constraint],
        total_constraints=1,
        hard_constraints=1,
        soft_constraints=0,
        review_flags=0,
        weather_data_available=True,
        freshness_summary="FRESH",
    )

    blackouts = get_weather_blackout_windows(response)
    assert len(blackouts) == 2
    r_ids = {b["resource_id"] for b in blackouts}
    assert "res-1" in r_ids
    assert "res-2" in r_ids
    assert blackouts[0]["start_at"] == forecast_time - timedelta(hours=2)
    assert blackouts[0]["end_at"] == forecast_time + timedelta(hours=2)


def test_penalty_tasks_extraction():
    forecast_time = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    alert = WeatherAlertItem(
        location_id="loc-1",
        location_name="Base North",
        forecast_timestamp=forecast_time,
        source_timestamp=forecast_time,
        variable="precipitation",
        observed_value=8.0,
        threshold=5.0,
        severity="WARNING",
        freshness="FRESH",
        explanation="Precipitation warning",
    )
    constraint = WeatherConstraint(
        alert=alert,
        constraint_type="SOFT_PENALTY",
        affected_task_ids=["task-1", "task-2"],
        penalty_weight=500,
        explanation="Precipitation penalty",
    )
    response = WeatherConstraintsResponse(
        scenario_id="scen-1",
        constraints=[constraint],
        total_constraints=1,
        hard_constraints=0,
        soft_constraints=1,
        review_flags=0,
        weather_data_available=True,
        freshness_summary="FRESH",
    )

    penalties = get_weather_penalty_tasks(response)
    assert penalties.get("task-1") == 500
    assert penalties.get("task-2") == 500
