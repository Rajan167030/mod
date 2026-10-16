"""
Location API Endpoints — CRUD + GeoJSON for synthetic demonstration locations.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user, require_roles
from app.core.permissions import UserRole
from app.core.errors import NotFoundError
from app.models.all_models import Scenario, User
from app.models.weather_models import Location
from app.services.audit_service import log_audit_event
from app.schemas.weather_schemas import (
    LocationCreate,
    LocationResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONProperties,
)

router = APIRouter(prefix="/locations", tags=["Locations"])


@router.get("", response_model=List[LocationResponse])
def list_locations(
    scenario_id: Optional[str] = Query(None, description="Filter by scenario ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List locations, optionally filtered by scenario."""
    query = db.query(Location)
    if scenario_id:
        # Validate scenario exists
        scenario = db.query(Scenario).filter_by(id=scenario_id).first()
        if not scenario:
            raise NotFoundError("Scenario", scenario_id)
        query = query.filter(Location.scenario_id == scenario_id)
    return query.order_by(Location.created_at.desc()).all()


@router.post("", response_model=LocationResponse, status_code=201)
def create_location(
    payload: LocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.PLANNER)),
):
    """Create a synthetic demonstration location."""
    # Validate scenario exists
    scenario = db.query(Scenario).filter_by(id=payload.scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", payload.scenario_id)

    location = Location(
        scenario_id=payload.scenario_id,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        location_type=payload.location_type,
        metadata_json=payload.metadata_json or {},
    )
    db.add(location)

    log_audit_event(
        db,
        action="LOCATION_CREATED",
        entity_type="Location",
        entity_id=location.id,
        actor=current_user,
        metadata={"name": payload.name, "scenario_id": payload.scenario_id},
    )

    db.commit()
    db.refresh(location)
    return location


@router.get("/geojson", response_model=GeoJSONFeatureCollection)
def get_locations_geojson(
    scenario_id: str = Query(..., description="Scenario ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get locations as a GeoJSON FeatureCollection for map rendering."""
    scenario = db.query(Scenario).filter_by(id=scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    locations = db.query(Location).filter_by(scenario_id=scenario_id).all()

    features = []
    for loc in locations:
        feature = GeoJSONFeature(
            geometry={
                "type": "Point",
                "coordinates": [loc.longitude, loc.latitude],  # GeoJSON uses [lon, lat]
            },
            properties=GeoJSONProperties(
                id=loc.id,
                name=loc.name,
                location_type=loc.location_type,
                scenario_id=loc.scenario_id,
                metadata=loc.metadata_json,
            ),
        )
        features.append(feature)

    return GeoJSONFeatureCollection(features=features)


@router.get("/{location_id}", response_model=LocationResponse)
def get_location(
    location_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single location by ID."""
    location = db.query(Location).filter_by(id=location_id).first()
    if not location:
        raise NotFoundError("Location", location_id)
    return location
