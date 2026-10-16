"""
Weather & Geospatial Data Models
Synthetic demonstration data only — no operational or classified information.
"""
import uuid
from datetime import datetime
from typing import Optional, Any, List

from sqlalchemy import (
    String, Text, Float, DateTime, ForeignKey, Index, CheckConstraint
)
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utc_now


def generate_uuid() -> str:
    return str(uuid.uuid4())


# Location types for synthetic demonstration
LOCATION_TYPES = ("BASE", "WAYPOINT", "WEATHER_STATION", "POI", "LOGISTICS_HUB")


class Location(Base):
    """
    A fictional geographic point associated with a scheduling scenario.
    All coordinates are synthetic and do not represent real operational sites.
    """
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location_type: Mapped[str] = mapped_column(String(50), default="POI", nullable=False)
    metadata_json: Mapped[Optional[Any]] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utc_now, nullable=False
    )

    # Relationships
    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="locations")
    weather_records: Mapped[List["WeatherRecord"]] = relationship(
        "WeatherRecord", back_populates="location", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_locations_scenario_id", "scenario_id"),
        Index("ix_locations_scenario_type", "scenario_id", "location_type"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_longitude_range"),
    )


# Freshness status values
FRESHNESS_STATUSES = ("FRESH", "STALE", "UNKNOWN")


class WeatherRecord(Base):
    """
    Normalized weather observation/forecast record for a location.
    Data is fetched from a configurable external weather provider and validated.
    """
    __tablename__ = "weather_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False, default="open-meteo")
    forecast_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utc_now, nullable=False
    )
    # Weather variables — nullable because not all providers supply all fields
    temperature_celsius: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wind_speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weather_condition: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Unit metadata for display
    units_json: Mapped[Optional[Any]] = mapped_column(
        JSON, default=dict, nullable=True
    )
    freshness_status: Mapped[str] = mapped_column(
        String(20), default="UNKNOWN", nullable=False
    )
    # Hash of raw response to avoid storing duplicate payloads
    raw_response_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utc_now, nullable=False
    )

    # Relationships
    location: Mapped["Location"] = relationship("Location", back_populates="weather_records")

    __table_args__ = (
        Index("ix_weather_location_forecast", "location_id", "forecast_timestamp"),
        Index("ix_weather_location_retrieved", "location_id", "retrieved_at"),
    )
