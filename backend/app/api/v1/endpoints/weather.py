"""
Weather API Endpoints — Current, Forecast, Alerts, and Refresh.
All data is sourced from a configurable weather provider (Open-Meteo by default).
"""
import time
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user, require_roles
from app.core.permissions import UserRole
from app.core.errors import NotFoundError
from app.models.all_models import Scenario, User
from app.models.weather_models import Location
from app.services.audit_service import log_audit_event
from app.services.weather_service import (
    get_current_weather,
    get_forecast_weather,
    get_weather_for_location,
    prefetch_weather,
    WeatherProviderError,
)
from app.services import weather_service
from app.services.weather_rules_service import get_alerts_for_scenario
from app.services.metar_service import get_nearest_metar
from app.schemas.weather_schemas import (
    WeatherCurrentResponse,
    WeatherForecastResponse,
    WeatherAlertsResponse,
    WeatherRefreshRequest,
    WeatherRefreshResponse,
    MetarResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather", tags=["Weather"])

# Simple rate limiter for refresh: track last refresh per scenario
_last_refresh: dict = {}
REFRESH_COOLDOWN_SECONDS = 60


@router.get("/current", response_model=WeatherCurrentResponse)
def get_current(
    location_id: str = Query(..., description="Location ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the most recent weather data for a location."""
    location = db.query(Location).filter_by(id=location_id).first()
    if not location:
        raise NotFoundError("Location", location_id)

    try:
        return get_current_weather(db, location)
    except WeatherProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Weather provider error: {str(e)}"
        )


@router.get("/forecast", response_model=WeatherForecastResponse)
def get_forecast(
    location_id: str = Query(..., description="Location ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get hourly weather forecast for a location."""
    location = db.query(Location).filter_by(id=location_id).first()
    if not location:
        raise NotFoundError("Location", location_id)

    try:
        return get_forecast_weather(db, location)
    except WeatherProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Weather provider error: {str(e)}"
        )


@router.get("/metar", response_model=MetarResponse)
def get_metar(
    location_id: str = Query(..., description="Location ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Latest METAR/TAF from the reporting station nearest to a location (NOAA AWC)."""
    location = db.query(Location).filter_by(id=location_id).first()
    if not location:
        raise NotFoundError("Location", location_id)
    return get_nearest_metar(location)


@router.get("/alerts", response_model=WeatherAlertsResponse)
def get_weather_alerts(
    scenario_id: str = Query(..., description="Scenario ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all weather-based alerts for a scenario."""
    scenario = db.query(Scenario).filter_by(id=scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    try:
        return get_alerts_for_scenario(db, scenario_id)
    except WeatherProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Weather provider error: {str(e)}"
        )


@router.post("/refresh", response_model=WeatherRefreshResponse)
def refresh_weather(
    payload: WeatherRefreshRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.PLANNER)),
):
    """
    Force-refresh weather data for a location or all locations in a scenario.
    Rate-limited to prevent excessive provider requests.
    """
    # Rate limiting
    rate_key = payload.location_id or payload.scenario_id or "global"
    last = _last_refresh.get(rate_key, 0)
    elapsed = time.time() - last
    if elapsed < REFRESH_COOLDOWN_SECONDS:
        remaining = int(REFRESH_COOLDOWN_SECONDS - elapsed)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Weather refresh rate limited. Try again in {remaining} seconds."
        )

    locations_to_refresh = []
    errors = []

    if payload.location_id:
        location = db.query(Location).filter_by(id=payload.location_id).first()
        if not location:
            raise NotFoundError("Location", payload.location_id)
        locations_to_refresh = [location]
    elif payload.scenario_id:
        scenario = db.query(Scenario).filter_by(id=payload.scenario_id).first()
        if not scenario:
            raise NotFoundError("Scenario", payload.scenario_id)
        locations_to_refresh = db.query(Location).filter_by(scenario_id=payload.scenario_id).all()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either location_id or scenario_id is required."
        )

    # Expire the cache for these sites and refetch them in a single provider request
    for loc in locations_to_refresh:
        weather_service._weather_cache.pop(loc.id, None)
        weather_service._failed_until.pop(loc.id, None)
    prefetch_weather(locations_to_refresh)

    refreshed = 0
    for loc in locations_to_refresh:
        try:
            data, _, _ = get_weather_for_location(db, loc)
            if data:
                refreshed += 1
            else:
                errors.append(f"{loc.name}: provider returned no data")
        except Exception as e:
            errors.append(f"{loc.name}: {str(e)}")

    _last_refresh[rate_key] = time.time()

    log_audit_event(
        db,
        action="WEATHER_REFRESH",
        entity_type="Weather",
        entity_id=payload.location_id or payload.scenario_id,
        actor=current_user,
        metadata={"refreshed_count": refreshed, "error_count": len(errors)},
    )
    db.commit()

    return WeatherRefreshResponse(
        success=not errors,
        refreshed_locations=refreshed,
        status="completed" if not errors else "partial",
        message=f"Refreshed weather data for {refreshed} location(s).",
        errors=errors,
    )
