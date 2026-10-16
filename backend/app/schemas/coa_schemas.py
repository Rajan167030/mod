"""Schemas for Courses of Action (alternative plans generated side by side)."""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class CoaRequest(BaseModel):
    include_weather: bool = True
    # Per-plan solver budget; the three plans are solved in parallel
    time_limit_seconds: int = 8


class CoaTaskOutcome(BaseModel):
    task_id: str
    task_name: str
    priority: str
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    delay_minutes: Optional[int] = None
    change: str  # UNCHANGED | REASSIGNED | RETIMED | NEW | DROPPED | UNASSIGNED
    weather_exposure: Optional[str] = None  # CRITICAL | WARNING


class CoaMetrics(BaseModel):
    assigned: int
    unassigned: int
    unassigned_critical: int
    unassigned_high: int
    total_delay_minutes: int
    critical_avg_delay_minutes: Optional[float] = None
    reassigned: int
    retimed: int
    unchanged: int
    finish_at: Optional[datetime] = None
    weather_exposed_critical: int
    weather_exposed_warning: int
    validator_pass: bool
    validator_conflicts: int


class CourseOfAction(BaseModel):
    key: str
    label: str
    intent: str
    solver_status: str
    objective_value: Optional[float] = None
    solve_seconds: float
    metrics: Optional[CoaMetrics] = None
    tasks: List[CoaTaskOutcome] = []
    recommended: bool = False
    note: Optional[str] = None
    # Key of an earlier course that produced the identical plan
    same_as: Optional[str] = None


class CoaSetResponse(BaseModel):
    coa_set_id: str
    baseline_version_id: str
    baseline_version_number: int
    include_weather: bool
    generated_at: datetime
    expires_at: datetime
    courses: List[CourseOfAction]
    recommendation_reason: Optional[str] = None
    # Metric name -> key of the COA that does best on it
    best_by_metric: Dict[str, List[str]] = {}


class CoaAdoptResponse(BaseModel):
    run_id: str
    proposed_version_id: Optional[str] = None
    proposed_version_number: Optional[int] = None
    status: str
