"""
Operational layers on top of aircraft and tasks: crews (duty and rest), stores
(weapons, countermeasures and mission kits) and zones (threats and airspace).
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, UTCDateTime, utc_now
from app.models.all_models import generate_uuid


class Crew(Base):
    """A flight crew. Every sortie needs one aircraft and one crew current on that aircraft type."""
    __tablename__ = "crews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Aircraft resource types this crew is current on, e.g. ["HEAVY_AIRCRAFT"]
    aircraft_types: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE", nullable=False)  # AVAILABLE, RESTING, UNFIT
    # Flying-duty limit for the planning period and the minimum rest between two sorties
    max_duty_minutes: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    min_rest_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # Duty already flown before the plan starts (counts against the limit and towards fatigue)
    duty_used_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Shift: the crew can only fly inside it. Null = no shift limit.
    duty_start: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    duty_end: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class StoreItem(Base):
    """Stock of one store type held for the scenario. Each sortie that needs it uses it up."""
    __tablename__ = "store_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    store_type: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. FLARE_SET, ROCKET_POD
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(30), default="WEAPON", nullable=False)  # WEAPON, COUNTERMEASURE, MISSION_KIT
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="each", nullable=False)


class OpsZone(Base):
    """
    A threat (SAM, AAA, MANPADS, radar) or airspace restriction, as a circle or polygon.
    BLOCK: sorties at a site inside it may not fly while it is active (unless the aircraft
    has the exempting capability, e.g. a defensive aids suite). AVOID: the solver avoids it.
    """
    __tablename__ = "ops_zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # THREAT, AIRSPACE
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # SAM, AAA, MANPADS, RADAR, RESTRICTED, NO_FLY
    effect: Mapped[str] = mapped_column(String(10), default="BLOCK", nullable=False)  # BLOCK, AVOID
    center_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    center_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    radius_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # [[lat, lon], ...] for polygons; null for circles
    polygon_json: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    active_from: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    active_until: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    exempt_capability: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)  # ELINT, HUMINT, NOTAM, ...
    confidence: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
