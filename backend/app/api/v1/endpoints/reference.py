"""Reference data for the theatre map (real Indian airfields, airspace, aircraft types, live METARs)."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.all_models import User
from app.services import reference_service

router = APIRouter(prefix="/reference", tags=["Reference data"])


@router.get("/airfields")
def airfields(user: User = Depends(get_current_user)):
    return {"source": "OurAirports (public domain)", "airfields": reference_service.airfields()}


@router.get("/airspace")
def airspace(user: User = Depends(get_current_user)):
    return {"source": "AAI eAIP India, ENR 5.1. Not for navigation.", "areas": reference_service.airspace()}


@router.get("/aircraft-types")
def aircraft_types(user: User = Depends(get_current_user)):
    return {"source": "Wikipedia (CC BY-SA 4.0)", "types": reference_service.aircraft_types()}


@router.get("/metar")
def metar(user: User = Depends(get_current_user)):
    return reference_service.metars()
