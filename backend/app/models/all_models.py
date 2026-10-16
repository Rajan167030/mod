import uuid
from datetime import datetime
from typing import Optional, List, Any
from sqlalchemy import (
    String, Text, Boolean, Integer, Float, DateTime, ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utc_now
from app.core.permissions import UserRole


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default=UserRole.VIEWER.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)

    # Relationships
    scenarios: Mapped[List["Scenario"]] = relationship("Scenario", back_populates="creator")
    audit_events: Mapped[List["AuditEvent"]] = relationship("AuditEvent", back_populates="actor")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, ARCHIVED, DRAFT
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    creator: Mapped[Optional["User"]] = relationship("User", back_populates="scenarios")
    resources: Mapped[List["Resource"]] = relationship("Resource", back_populates="scenario", cascade="all, delete-orphan")
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="scenario", cascade="all, delete-orphan")
    schedules: Mapped[List["ScheduleVersion"]] = relationship("ScheduleVersion", back_populates="scenario", cascade="all, delete-orphan")
    disruptions: Mapped[List["Disruption"]] = relationship("Disruption", back_populates="scenario", cascade="all, delete-orphan")
    locations: Mapped[List["Location"]] = relationship("Location", back_populates="scenario", cascade="all, delete-orphan")


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., TRANSPORT_AIRCRAFT, HELICOPTER, CREW_SQUAD, MAINTENANCE_BAY
    status: Mapped[str] = mapped_column(String(50), default="AVAILABLE", nullable=False)  # AVAILABLE, MAINTENANCE, GROUNDED
    metadata_json: Mapped[Optional[Any]] = mapped_column(JSON, default=dict, nullable=True)

    # Relationships
    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="resources")
    availabilities: Mapped[List["ResourceAvailability"]] = relationship("ResourceAvailability", back_populates="resource", cascade="all, delete-orphan")
    assignments: Mapped[List["Assignment"]] = relationship("Assignment", back_populates="resource")


class ResourceAvailability(Base):
    __tablename__ = "resource_availabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    resource: Mapped["Resource"] = relationship("Resource", back_populates="availabilities")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    earliest_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    latest_finish: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    priority: Mapped[str] = mapped_column(String(50), default="MEDIUM", nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, SCHEDULED, BLOCKED, COMPLETED
    # Site the task operates at; its weather limits apply to this task only. Null = not site-specific.
    location_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="tasks")
    requirements: Mapped[List["TaskRequirement"]] = relationship("TaskRequirement", back_populates="task", cascade="all, delete-orphan")
    assignments: Mapped[List["Assignment"]] = relationship("Assignment", back_populates="task")


class TaskRequirement(Base):
    __tablename__ = "task_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_type: Mapped[str] = mapped_column(String(100), nullable=False)  # QUALIFICATION, RESOURCE_TYPE, PAYLOAD_CAPACITY
    requirement_value: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="requirements")


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("schedule_versions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)  # DRAFT, PROPOSED, APPROVED, REJECTED, SUPERSEDED
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)

    # Relationships
    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="schedules")
    parent_version: Mapped[Optional["ScheduleVersion"]] = relationship("ScheduleVersion", remote_side=[id])
    assignments: Mapped[List["Assignment"]] = relationship("Assignment", back_populates="schedule_version", cascade="all, delete-orphan")
    optimisation_runs: Mapped[List["OptimisationRun"]] = relationship("OptimisationRun", back_populates="schedule_version", cascade="all, delete-orphan")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    schedule_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedule_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    # Relationships
    schedule_version: Mapped["ScheduleVersion"] = relationship("ScheduleVersion", back_populates="assignments")
    task: Mapped["Task"] = relationship("Task", back_populates="assignments")
    resource: Mapped["Resource"] = relationship("Resource", back_populates="assignments")


class Disruption(Base):
    __tablename__ = "disruptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)  # RESOURCE_UNAVAILABLE, WINDOW_SHIFT, DURATION_SURGE, DEADLINE_TIGHTEN, CAPACITY_DROP
    payload_json: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)

    # Relationships
    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="disruptions")


class OptimisationRun(Base):
    __tablename__ = "optimisation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    schedule_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedule_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    solver_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN
    objective_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metrics_json: Mapped[Optional[Any]] = mapped_column(JSON, default=dict, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    schedule_version: Mapped["ScheduleVersion"] = relationship("ScheduleVersion", back_populates="optimisation_runs")
    approvals: Mapped[List["Approval"]] = relationship("Approval", back_populates="optimisation_run", cascade="all, delete-orphan")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    optimisation_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("optimisation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)  # APPROVED, REJECTED
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False)

    # Relationships
    optimisation_run: Mapped["OptimisationRun"] = relationship("OptimisationRun", back_populates="approvals")
    reviewer: Mapped["User"] = relationship("User")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[Optional[Any]] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, nullable=False, index=True)

    # Relationships
    actor: Mapped[Optional["User"]] = relationship("User", back_populates="audit_events")
