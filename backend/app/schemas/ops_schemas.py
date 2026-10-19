from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.all_schemas import as_utc

ZONE_CATEGORIES = ("THREAT", "AIRSPACE")
ZONE_KINDS = ("SAM", "AAA", "MANPADS", "RADAR", "RESTRICTED", "NO_FLY")
ZONE_EFFECTS = ("BLOCK", "AVOID")
CREW_STATUSES = ("AVAILABLE", "RESTING", "UNFIT")
STORE_CATEGORIES = ("WEAPON", "COUNTERMEASURE", "MISSION_KIT")


def _pick(value: Optional[str], allowed: tuple, field: str) -> Optional[str]:
    if value is None:
        return None
    v = value.strip().upper()
    if v not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

class ZoneBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    category: str
    kind: str
    effect: str = "BLOCK"
    center_lat: Optional[float] = Field(None, ge=-90, le=90)
    center_lon: Optional[float] = Field(None, ge=-180, le=180)
    radius_km: Optional[float] = Field(None, gt=0, le=500)
    polygon: Optional[List[List[float]]] = None
    active_from: Optional[datetime] = None
    active_until: Optional[datetime] = None
    exempt_capability: Optional[str] = Field(None, max_length=60)
    source: Optional[str] = Field(None, max_length=60)
    confidence: float = Field(0.8, ge=0, le=1)
    notes: Optional[str] = None

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        return _pick(v, ZONE_CATEGORIES, "category")

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        return _pick(v, ZONE_KINDS, "kind")

    @field_validator("effect")
    @classmethod
    def _effect(cls, v):
        return _pick(v, ZONE_EFFECTS, "effect")

    @field_validator("active_from", "active_until")
    @classmethod
    def _utc(cls, v):
        return as_utc(v)

    @field_validator("exempt_capability")
    @classmethod
    def _cap(cls, v):
        return (v.strip().upper() or None) if v else None

    @model_validator(mode="after")
    def _shape(self):
        circle = self.center_lat is not None and self.center_lon is not None and self.radius_km
        if self.polygon:
            if len(self.polygon) < 3 or any(len(p) != 2 or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180) for p in self.polygon):
                raise ValueError("polygon needs at least 3 [lat, lon] points")
        elif not circle:
            raise ValueError("give either center_lat, center_lon and radius_km, or a polygon")
        if self.active_from and self.active_until and self.active_until <= self.active_from:
            raise ValueError("active_until must be after active_from")
        return self


class ZoneCreate(ZoneBase):
    pass


class ZoneResponse(BaseModel):
    id: str
    scenario_id: str
    name: str
    category: str
    kind: str
    effect: str
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    radius_km: Optional[float] = None
    polygon: Optional[List[List[float]]] = None
    active_from: Optional[datetime] = None
    active_until: Optional[datetime] = None
    exempt_capability: Optional[str] = None
    source: Optional[str] = None
    confidence: float
    notes: Optional[str] = None
    created_at: datetime
    affected_tasks: List[Dict[str, Any]] = []
    active_now: bool = False


# ---------------------------------------------------------------------------
# Crews and stores
# ---------------------------------------------------------------------------

class CrewCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    aircraft_types: List[str] = []
    status: str = "AVAILABLE"
    max_duty_minutes: int = Field(600, ge=30, le=24 * 60)
    min_rest_minutes: int = Field(60, ge=0, le=24 * 60)
    duty_used_minutes: int = Field(0, ge=0, le=24 * 60)
    duty_start: Optional[datetime] = None
    duty_end: Optional[datetime] = None
    notes: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _pick(v, CREW_STATUSES, "status")

    @field_validator("duty_start", "duty_end")
    @classmethod
    def _utc(cls, v):
        return as_utc(v)


class CrewUpdate(BaseModel):
    status: Optional[str] = None
    max_duty_minutes: Optional[int] = Field(None, ge=30, le=24 * 60)
    min_rest_minutes: Optional[int] = Field(None, ge=0, le=24 * 60)
    duty_used_minutes: Optional[int] = Field(None, ge=0, le=24 * 60)
    aircraft_types: Optional[List[str]] = None
    notes: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _pick(v, CREW_STATUSES, "status")


class CrewResponse(BaseModel):
    id: str
    scenario_id: str
    name: str
    aircraft_types: List[str]
    status: str
    max_duty_minutes: int
    min_rest_minutes: int
    duty_used_minutes: int
    duty_start: Optional[datetime] = None
    duty_end: Optional[datetime] = None
    notes: Optional[str] = None
    # From the active plan
    planned_sorties: int = 0
    planned_minutes: int = 0
    duty_ratio: float = 0.0
    next_sortie_at: Optional[datetime] = None


class StoreCreate(BaseModel):
    store_type: str = Field(..., min_length=2, max_length=60)
    name: str = Field(..., min_length=2, max_length=120)
    category: str = "WEAPON"
    quantity: int = Field(..., ge=0, le=100000)
    unit: str = Field("each", max_length=20)

    @field_validator("store_type")
    @classmethod
    def _type(cls, v):
        return v.strip().upper().replace(" ", "_")

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        return _pick(v, STORE_CATEGORIES, "category")


class StoreUpdate(BaseModel):
    quantity: int = Field(..., ge=0, le=100000)


class StoreResponse(BaseModel):
    id: str
    scenario_id: str
    store_type: str
    name: str
    category: str
    quantity: int
    unit: str
    planned_use: int = 0
    demand: int = 0
    carriers: List[str] = []
