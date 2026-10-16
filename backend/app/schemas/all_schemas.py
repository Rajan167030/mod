from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


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


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ScenarioResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

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
    resource_type: str
    status: str = "AVAILABLE"
    metadata_json: Optional[Dict[str, Any]] = None


class ResourceUpdate(BaseModel):
    name: Optional[str] = None
    resource_type: Optional[str] = None
    status: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None


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


class TaskCreate(BaseModel):
    scenario_id: str
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    duration_minutes: int = Field(..., gt=0)
    earliest_start: datetime
    latest_finish: datetime
    priority: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW
    status: str = "PENDING"
    location_id: Optional[str] = None
    requirements: List[TaskRequirementSchema] = []


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    earliest_start: Optional[datetime] = None
    latest_finish: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None


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
    solver_time_limit_seconds: Optional[int] = 30
    weight_unassigned: Optional[int] = 10000
    weight_delay: Optional[int] = 5
    weight_churn: Optional[int] = 50
    weight_makespan: Optional[int] = 1
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
