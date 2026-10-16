"""
Weather Rules Engine — Threshold-Based Alert Generation
Compares normalized weather data with configurable demonstration thresholds.
All thresholds are illustrative and editable — not real aviation or military safety standards.
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.weather_models import Location
from app.schemas.weather_schemas import (
    WeatherAlertItem,
    WeatherAlertsResponse,
    WeatherThresholdConfig,
)
from app.services.weather_service import (
    get_weather_for_location,
    classify_freshness,
    prefetch_weather,
)

logger = logging.getLogger(__name__)


def get_default_thresholds() -> WeatherThresholdConfig:
    """Load demonstration thresholds from application config."""
    return WeatherThresholdConfig(
        wind_speed_warning_kmh=settings.WEATHER_WIND_WARNING_KMH,
        wind_speed_critical_kmh=settings.WEATHER_WIND_CRITICAL_KMH,
        precipitation_warning_mm=settings.WEATHER_PRECIP_WARNING_MM,
        precipitation_critical_mm=settings.WEATHER_PRECIP_CRITICAL_MM,
        temperature_low_warning_celsius=settings.WEATHER_TEMP_LOW_WARNING_C,
        temperature_low_critical_celsius=settings.WEATHER_TEMP_LOW_CRITICAL_C,
    )


def evaluate_weather_rules(
    data_points: List[Dict[str, Any]],
    location: Location,
    freshness: str,
    retrieved_at_ts: Optional[float],
    thresholds: Optional[WeatherThresholdConfig] = None,
) -> List[WeatherAlertItem]:
    """
    Evaluate normalized weather data against configurable thresholds.
    Generates structured alerts with full context for each rule violation.
    Never treats missing data as safe conditions.
    """
    if thresholds is None:
        thresholds = get_default_thresholds()

    alerts: List[WeatherAlertItem] = []
    source_ts = (
        datetime.fromtimestamp(retrieved_at_ts, tz=timezone.utc)
        if retrieved_at_ts
        else None
    )

    # If no data is available, generate an alert about missing data
    if not data_points:
        alerts.append(WeatherAlertItem(
            location_id=location.id,
            location_name=location.name,
            forecast_timestamp=datetime.now(timezone.utc),
            variable="all",
            observed_value=0.0,
            threshold=0.0,
            severity="WARNING",
            freshness="UNKNOWN",
            explanation=(
                f"No weather data available for '{location.name}'. "
                f"Missing data must not be treated as safe conditions. "
                f"Manual assessment required."
            ),
            source_timestamp=source_ts,
        ))
        return alerts

    for dp in data_points:
        try:
            fc_ts = datetime.fromisoformat(
                dp["forecast_timestamp"].replace("Z", "+00:00")
            )
        except (ValueError, AttributeError, TypeError):
            continue

        # --- Wind Speed Rules ---
        wind = dp.get("wind_speed_kmh")
        if wind is not None:
            if wind >= thresholds.wind_speed_critical_kmh:
                alerts.append(WeatherAlertItem(
                    location_id=location.id,
                    location_name=location.name,
                    forecast_timestamp=fc_ts,
                    variable="wind_speed",
                    observed_value=wind,
                    threshold=thresholds.wind_speed_critical_kmh,
                    severity="CRITICAL",
                    freshness=freshness,
                    explanation=(
                        f"Wind speed {wind} km/h exceeds CRITICAL demonstration threshold "
                        f"of {thresholds.wind_speed_critical_kmh} km/h at '{location.name}'. "
                        f"(Illustrative threshold — not an operational safety standard.)"
                    ),
                    source_timestamp=source_ts,
                ))
            elif wind >= thresholds.wind_speed_warning_kmh:
                alerts.append(WeatherAlertItem(
                    location_id=location.id,
                    location_name=location.name,
                    forecast_timestamp=fc_ts,
                    variable="wind_speed",
                    observed_value=wind,
                    threshold=thresholds.wind_speed_warning_kmh,
                    severity="WARNING",
                    freshness=freshness,
                    explanation=(
                        f"Wind speed {wind} km/h exceeds WARNING demonstration threshold "
                        f"of {thresholds.wind_speed_warning_kmh} km/h at '{location.name}'. "
                        f"(Illustrative threshold — not an operational safety standard.)"
                    ),
                    source_timestamp=source_ts,
                ))

        # --- Precipitation Rules ---
        precip = dp.get("precipitation_mm")
        if precip is not None:
            if precip >= thresholds.precipitation_critical_mm:
                alerts.append(WeatherAlertItem(
                    location_id=location.id,
                    location_name=location.name,
                    forecast_timestamp=fc_ts,
                    variable="precipitation",
                    observed_value=precip,
                    threshold=thresholds.precipitation_critical_mm,
                    severity="CRITICAL",
                    freshness=freshness,
                    explanation=(
                        f"Precipitation {precip} mm exceeds CRITICAL demonstration threshold "
                        f"of {thresholds.precipitation_critical_mm} mm at '{location.name}'. "
                        f"(Illustrative threshold — not an operational safety standard.)"
                    ),
                    source_timestamp=source_ts,
                ))
            elif precip >= thresholds.precipitation_warning_mm:
                alerts.append(WeatherAlertItem(
                    location_id=location.id,
                    location_name=location.name,
                    forecast_timestamp=fc_ts,
                    variable="precipitation",
                    observed_value=precip,
                    threshold=thresholds.precipitation_warning_mm,
                    severity="WARNING",
                    freshness=freshness,
                    explanation=(
                        f"Precipitation {precip} mm exceeds WARNING demonstration threshold "
                        f"of {thresholds.precipitation_warning_mm} mm at '{location.name}'. "
                        f"(Illustrative threshold — not an operational safety standard.)"
                    ),
                    source_timestamp=source_ts,
                ))

        # --- Temperature Rules (low temperature) ---
        temp = dp.get("temperature_celsius")
        if temp is not None:
            if temp <= thresholds.temperature_low_critical_celsius:
                alerts.append(WeatherAlertItem(
                    location_id=location.id,
                    location_name=location.name,
                    forecast_timestamp=fc_ts,
                    variable="temperature",
                    observed_value=temp,
                    threshold=thresholds.temperature_low_critical_celsius,
                    severity="CRITICAL",
                    freshness=freshness,
                    explanation=(
                        f"Temperature {temp}°C is at or below CRITICAL demonstration threshold "
                        f"of {thresholds.temperature_low_critical_celsius}°C at '{location.name}'. "
                        f"(Illustrative threshold — not an operational safety standard.)"
                    ),
                    source_timestamp=source_ts,
                ))
            elif temp <= thresholds.temperature_low_warning_celsius:
                alerts.append(WeatherAlertItem(
                    location_id=location.id,
                    location_name=location.name,
                    forecast_timestamp=fc_ts,
                    variable="temperature",
                    observed_value=temp,
                    threshold=thresholds.temperature_low_warning_celsius,
                    severity="WARNING",
                    freshness=freshness,
                    explanation=(
                        f"Temperature {temp}°C is at or below WARNING demonstration threshold "
                        f"of {thresholds.temperature_low_warning_celsius}°C at '{location.name}'. "
                        f"(Illustrative threshold — not an operational safety standard.)"
                    ),
                    source_timestamp=source_ts,
                ))

    return alerts


def get_alerts_for_location(
    db: Session,
    location: Location,
    thresholds: Optional[WeatherThresholdConfig] = None,
) -> List[WeatherAlertItem]:
    """Get weather alerts for a single location."""
    data, freshness, ts = get_weather_for_location(db, location)
    return evaluate_weather_rules(data, location, freshness, ts, thresholds)


def _exercise_inject_alerts(db: Session, scenario_id: str, locations: Dict[str, Location]) -> List[WeatherAlertItem]:
    """One alert per hour of each simulated weather inject in this scenario, clearly labelled."""
    from datetime import timedelta
    from app.models.replay_models import WeatherInject

    out: List[WeatherAlertItem] = []
    for inj in db.query(WeatherInject).filter(WeatherInject.scenario_id == scenario_id).all():
        loc = locations.get(inj.location_id)
        if not loc:
            continue
        start = inj.start_at if inj.start_at.tzinfo else inj.start_at.replace(tzinfo=timezone.utc)
        end = inj.end_at if inj.end_at.tzinfo else inj.end_at.replace(tzinfo=timezone.utc)
        h = start.replace(minute=0, second=0, microsecond=0)
        while h < end:
            out.append(WeatherAlertItem(
                location_id=loc.id,
                location_name=loc.name,
                forecast_timestamp=h,
                variable=inj.variable,
                observed_value=inj.value,
                threshold=inj.value,
                severity=inj.severity,
                freshness="FRESH",
                explanation=f"EXERCISE INJECT (simulated): {inj.note or inj.variable} at '{loc.name}'.",
                source_timestamp=inj.created_at,
                source="exercise",
            ))
            h += timedelta(hours=1)
    return out


def get_alerts_for_scenario(
    db: Session,
    scenario_id: str,
    thresholds: Optional[WeatherThresholdConfig] = None,
) -> WeatherAlertsResponse:
    """Get all weather alerts for every location in a scenario."""
    if thresholds is None:
        thresholds = get_default_thresholds()
    locations = db.query(Location).filter_by(scenario_id=scenario_id).all()

    all_alerts: List[WeatherAlertItem] = []
    freshness_set = set()

    # One provider request for every site that needs fresh data, then evaluate from cache
    prefetch_weather(locations)

    for loc in locations:
        data, freshness, ts = get_weather_for_location(db, loc)
        all_alerts.extend(evaluate_weather_rules(data, loc, freshness, ts, thresholds))
        freshness_set.add(freshness)

    all_alerts.extend(_exercise_inject_alerts(db, scenario_id, {loc.id: loc for loc in locations}))

    critical = sum(1 for a in all_alerts if a.severity == "CRITICAL")
    warning = sum(1 for a in all_alerts if a.severity == "WARNING")
    info = sum(1 for a in all_alerts if a.severity == "INFO")

    # Aggregate freshness: worst case wins
    if "UNKNOWN" in freshness_set:
        summary_freshness = "UNKNOWN"
    elif "STALE" in freshness_set:
        summary_freshness = "STALE"
    elif "FRESH" in freshness_set:
        summary_freshness = "FRESH"
    else:
        summary_freshness = "UNKNOWN"

    return WeatherAlertsResponse(
        scenario_id=scenario_id,
        alerts=all_alerts,
        total_alerts=len(all_alerts),
        critical_count=critical,
        warning_count=warning,
        info_count=info,
        freshness_summary=summary_freshness,
        thresholds_used=thresholds,
    )
