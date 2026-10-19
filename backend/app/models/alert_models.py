"""User-defined alert rules, evaluated against a scenario's active plan on demand."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utc_now
from app.models.all_models import generate_uuid


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # CRITICAL_UNASSIGNED, TASK_DELAY, WEATHER_EXPOSURE, RULE_CONFLICTS, AIRCRAFT_HOURS, SINGLE_SOURCE
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_priority: Mapped[str] = mapped_column(String(16), default="HIGH", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="WARNING", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
