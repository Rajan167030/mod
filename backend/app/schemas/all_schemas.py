from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator

SCENARIO_STATUSES = ("ACTIVE", "ARCHIVED", "DRAFT")
RESOURCE_STATUSES = ("AVAILABLE", "MAINTENANCE", "GROUNDED", "UNAVAILABLE")
TASK_PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
TASK_STATUSES = ("PENDING", "SCHEDULED", "BLOCKED", "COMPLETED")


def _one_of(value: Optional[str], allowed: tuple, field: str) -> Optional[str]:
    """Case-insensitive enum check; returns the canonical upper-case value."""
    if value is None:
        return None
    v = value.strip().upper()
    if v not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}")
    return v


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Treat a timestamp without an offset as UTC so naive and aware inputs compare safely."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _no_nulls(model: BaseModel, fields: tuple) -> None:
    """PATCH bodies may omit these fields but not set them to null (the columns are NOT NULL)."""
    for f in fields:
        if f in model.model_fields_set and getattr(model, f) is None:
            raise ValueError(f"{f} cannot be null")


# ==============================
# Common & Pagination
# ==============================
class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int


# ==============================
# Authentication Schemas
# ==============================
class LoginRequest(BaseModel):
    email: str
    password: str



class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ==============================
# Scenario Schemas
# ==============================
class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    status: str = "ACTIVE"

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _one_of(v, SCENARIO_STATUSES, "status")


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _one_of(v, SCENARIO_STATUSES, "status")

    @model_validator(mode="after")
    def _required(self):
        _no_nulls(self, ("name", "status"))
        return self


class ScenarioResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    parent_scenario_id: Optional[str] = None

    class Config:
        from_attributes = True


# ==============================
# Resource Schemas
# ==============================
class ResourceAvailabilitySchema(BaseModel):
    id: Optional[str] = None
    start_at: datetime
    end_at: datetime
    available: bool = True

    class Config:
        from_attributes = True


class ResourceCreate(BaseModel):
    scenario_id: str
    name: str = Field(..., min_length=2, max_length=255)
    resource_type: str = Field(..., min_length=1, max_length=50)
    status: str = "AVAILABLE"
    metadata_json: Optional[Dict[str, Any]] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _one_of(v, RESOURCE_STATUSES, "status")


class ResourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    resource_type: Optional[str] = Field(None, min_length=1, max_length=50)
    status: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _one_of(v, RESOURCE_STATUSES, "status")

    @model_validator(mode="after")
    def _required(self):
        _no_nulls(self, ("name", "resource_type", "status"))
        return self


class ResourceResponse(BaseModel):
    id: str
    scenario_id: str
    name: str
    resource_type: str
    status: str
    metadata_json: Optional[Dict[str, Any]] = None
    availabilities: List[ResourceAvailabilitySchema] = []

    class Config:
        from_attributes = True


# ==============================
# Task Schemas
# ==============================
class TaskRequirementSchema(BaseModel):
    id: Optional[str] = None
    requirement_type: str
    requirement_value: str

    class Config:
        from_attributes = True


def check_task_window(earliest_start: datetime, latest_finish: datetime, duration_minutes: int) -> None:
    """A task must finish after it can start, and its window must be long enough to fly it."""
    window = (as_utc(latest_finish) - as_utc(earliest_start)).total_seconds() / 60
    if window <= 0:
        raise ValueError("latest_finish must be after earliest_start")
    if duration_minutes > window:
        raise ValueError(f"duration_minutes ({duration_minutes}) is longer than the {int(window)}-minute window")


class TaskCreate(BaseModel):
    scenario_id: str
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    duration_minutes: int = Field(..., gt=0, le=7 * 24 * 60)
    earliest_start: datetime
    latest_finish: datetime
    priority: str = "MEDIUM"
    status: str = "PENDING"
    location_id: Optional[str] = None
    requirements: List[TaskRequirementSchema] = []

    @field_validator("earliest_start", "latest_finish")
    @classmethod
    def _utc(cls, v):
        return as_utc(v)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        return _one_of(v, TASK_PRIORITIES, "priority")

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _one_of(v, TASK_STATUSES, "status")

    @model_validator(mode="after")
    def _window(self):
        check_task_window(self.earliest_start, self.latest_finish, self.duration_minutes)
        return self


class TaskUpdate(BaseModel):
    """Partial update; the endpoint re-checks the window against the stored values."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, gt=0, le=7 * 24 * 60)
    earliest_start: Optional[datetime] = None
    latest_finish: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None

    @field_validator("earliest_start", "latest_finish")
    @classmethod
    def _utc(cls, v):
        return as_utc(v)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        return _one_of(v, TASK_PRIORITIES, "priority")

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        return _one_of(v, TASK_STATUSES, "status")

    @model_validator(mode="after")
    def _required(self):
        _no_nulls(self, ("name", "duration_minutes", "earliest_start", "latest_finish", "priority", "status"))
        return self


class TaskResponse(BaseModel):
    id: str
    scenario_id: str
    name: str
    description: Optional[str] = None
    duration_minutes: int
    earliest_start: datetime
    latest_finish: datetime
    priority: str
    status: str
    location_id: Optional[str] = None
    requirements: List[TaskRequirementSchema] = []

    class Config:
        from_attributes = True


# ==============================
# Schedule & Assignment Schemas
# ==============================
class AssignmentResponse(BaseModel):
    id: str
    schedule_version_id: str
    task_id: str
    resource_id: str
    start_at: datetime
    end_at: datetime
    task_name: Optional[str] = None
    resource_name: Optional[str] = None
    priority: Optional[str] = None
    task_location_id: Optional[str] = None
    crew_id: Optional[str] = None
    crew_name: Optional[str] = None

    class Config:
        from_attributes = True


class ScheduleVersionResponse(BaseModel):
    id: str
    scenario_id: str
    version_number: int
    parent_version_id: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    assignments: List[AssignmentResponse] = []

    class Config:
        from_attributes = True


# ==============================
# Conflict & Validation Schemas
# ==============================
class ConflictItem(BaseModel):
    code: str  # OVERLAP, AVAILABILITY_BREACH, TIME_WINDOW_VIOLATION, ELIGIBILITY_MISMATCH, DOUBLE_BOOKING
    severity: str  # CRITICAL, WARNING
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None
    task_ids: List[str] = []
    task_names: List[str] = []
    conflict_start: Optional[datetime] = None
    conflict_end: Optional[datetime] = None
    explanation: str


class ValidationResult(BaseModel):
    schedule_id: str
    is_valid: bool
    total_assignments: int
    conflict_count: int
    conflicts: List[ConflictItem] = []
    unassigned_task_count: int = 0
    unassigned_task_ids: List[str] = []


# ==============================
# Disruption Schemas
# ==============================
class DisruptionCreate(BaseModel):
    scenario_id: str
    type: str  # RESOURCE_UNAVAILABLE, WINDOW_SHIFT, DURATION_SURGE, DEADLINE_TIGHTEN, CAPACITY_DROP
    payload_json: Dict[str, Any]


class DisruptionResponse(BaseModel):
    id: str
    scenario_id: str
    type: str
    payload_json: Dict[str, Any]
    created_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==============================
# Optimisation Schemas
# ==============================
class OptimisationRunRequest(BaseModel):
    schedule_id: str
    # CP-SAT rejects very large limits, and a long run would hold a worker for that long
    solver_time_limit_seconds: Optional[int] = Field(30, ge=1, le=300)
    # Negative weights would reward leaving tasks unassigned or late
    weight_unassigned: Optional[int] = Field(10000, ge=0, le=1_000_000)
    weight_delay: Optional[int] = Field(5, ge=0, le=1_000_000)
    weight_churn: Optional[int] = Field(50, ge=0, le=1_000_000)
    weight_makespan: Optional[int] = Field(1, ge=0, le=1_000_000)
    include_weather: Optional[bool] = False


class OptimisationRunResponse(BaseModel):
    id: str
    schedule_version_id: str
    new_schedule_version_id: Optional[str] = None
    status: str
    solver_status: Optional[str] = None
    objective_value: Optional[float] = None
    metrics_json: Optional[Dict[str, Any]] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    error_summary: Optional[str] = None
    validation: Optional[ValidationResult] = None
    advisory_explanation: Optional[str] = None

    class Config:
        from_attributes = True


class ScheduleComparison(BaseModel):
    baseline_version_id: str
    proposed_version_id: str
    baseline_version_number: int
    proposed_version_number: int
    total_tasks: int
    baseline_assigned: int
    proposed_assigned: int
    tasks_reassigned: int
    tasks_time_shifted: int
    total_delay_minutes_baseline: int
    total_delay_minutes_proposed: int
    delay_change_minutes: int
    changes: List[Dict[str, Any]] = []


# ==============================
# Review & Approval Schemas
# ==============================
class ApprovalDecisionRequest(BaseModel):
    decision: str  # APPROVED, REJECTED
    reason: str = Field(..., min_length=3)


class ApprovalResponse(BaseModel):
    id: str
    optimisation_run_id: str
    reviewer_id: str
    reviewer_email: Optional[str] = None
    decision: str
    reason: str
    created_at: datetime

    class Config:
        from_attributes = True


# ==============================
# Audit Event Schemas
# ==============================
class AuditEventResponse(BaseModel):
    id: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==============================
# Reports & Dashboard KPI Schemas
# ==============================
class DashboardKPI(BaseModel):
    scenario_id: Optional[str] = None
    scenario_name: Optional[str] = None
    active_version_number: Optional[int] = None
    total_scenarios: int
    total_resources: int
    total_tasks: int
    assigned_tasks: int
    unassigned_tasks: int
    active_conflicts: int
    latest_optimisation_status: Optional[str] = None
    schedule_completion_rate: float
    resource_utilization_rate: float
    recent_audits: List[AuditEventResponse] = []
