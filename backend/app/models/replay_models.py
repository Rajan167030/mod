"""
Live exercise replay: a timed script of events played against a copy of a scenario,
and simulated weather injects that exist only inside such an exercise.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utc_now
from app.models.all_models import generate_uuid


class ReplaySession(Base):
    __tablename__ = "replay_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    # The exercise copy the events are applied to (deleted with the session)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    source_scenario_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    script_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", nullable=False)  # RUNNING, PAUSED, FINISHED
    speed: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)  # simulated seconds per real second
    sim_t0: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # Simulated time reached when the clock was last re-anchored (start, pause, resume, speed change)
    sim_anchor: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    wall_anchor: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    events_json: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)


class WeatherInject(Base):
    """Simulated weather for exercises. Always labelled as such; never mixed into real forecasts silently."""

    __tablename__ = "weather_injects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    variable: Mapped[str] = mapped_column(String(32), nullable=False)  # wind_speed, precipitation, temperature
    value: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # WARNING, CRITICAL
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
