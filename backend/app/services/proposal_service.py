"""
Shared steps for turning a solver result into a reviewable proposal.
Used by the single-run optimiser and by Courses of Action adoption.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.engine.solver import ScheduleSolverResult
from app.models.all_models import (
    Assignment,
    OptimisationRun,
    Resource,
    ResourceAvailability,
    Scenario,
    ScheduleVersion,
    Task,
    User,
)
from app.schemas.all_schemas import ValidationResult
from app.services.conflict_service import check_schedule_conflicts


@dataclass
class SolverInputs:
    baseline: ScheduleVersion
    scenario: Scenario
    resources: List[Resource]
    availabilities: List[ResourceAvailability]
    tasks: List[Task]
    baseline_assignments: List[Assignment]


def load_solver_inputs(db: Session, schedule_id: str) -> SolverInputs:
    baseline = db.query(ScheduleVersion).filter(ScheduleVersion.id == schedule_id).first()
    if not baseline:
        raise NotFoundError("ScheduleVersion", schedule_id)
    sid = baseline.scenario_id
    return SolverInputs(
        baseline=baseline,
        scenario=db.query(Scenario).filter(Scenario.id == sid).first(),
        resources=db.query(Resource).filter(Resource.scenario_id == sid).all(),
        availabilities=db.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == sid).all(),
        tasks=db.query(Task).filter(Task.scenario_id == sid).all(),
        baseline_assignments=db.query(Assignment).filter(Assignment.schedule_version_id == schedule_id).all(),
    )


def _add_version(
    db: Session,
    baseline: ScheduleVersion,
    assignments: List[Dict[str, Any]],
    status: str,
    created_by: Optional[str],
) -> ScheduleVersion:
    version_count = db.query(ScheduleVersion).filter(ScheduleVersion.scenario_id == baseline.scenario_id).count()
    version = ScheduleVersion(
        scenario_id=baseline.scenario_id,
        version_number=version_count + 1,
        parent_version_id=baseline.id,
        status=status,
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    for a in assignments:
        db.add(Assignment(
            schedule_version_id=version.id,
            task_id=a["task_id"],
            resource_id=a["resource_id"],
            crew_id=a.get("crew_id"),
            start_at=a["start_at"],
            end_at=a["end_at"],
            exec_status=a.get("exec_status") or "PLANNED",
            actual_start=a.get("actual_start"),
            actual_end=a.get("actual_end"),
        ))
    db.flush()
    return version


def validate_without_saving(db: Session, baseline: ScheduleVersion, assignments: List[Dict[str, Any]]) -> ValidationResult:
    """Run the independent validator on candidate assignments inside a savepoint, then discard them."""
    savepoint = db.begin_nested()
    try:
        version = _add_version(db, baseline, assignments, status="DRAFT", created_by=None)
        result = check_schedule_conflicts(db, version.id)
    finally:
        savepoint.rollback()
    return result


def persist_proposal(
    db: Session,
    baseline: ScheduleVersion,
    result: ScheduleSolverResult,
    user: User,
    started_at: datetime,
    finished_at: datetime,
) -> tuple[Optional[ScheduleVersion], OptimisationRun, Optional[ValidationResult]]:
    """
    Store a solver result: a PROPOSED schedule version (when feasible) plus the OptimisationRun
    that produced it. Nothing becomes active until a reviewer approves the run.
    """
    version = None
    validation = None
    if result.solver_status in ("OPTIMAL", "FEASIBLE"):
        version = _add_version(db, baseline, result.assignments, status="PROPOSED", created_by=user.id)
        validation = check_schedule_conflicts(db, version.id)

    run = OptimisationRun(
        # A run's schedule_version_id holds the version it produced (the baseline when solving failed)
        schedule_version_id=version.id if version else baseline.id,
        status="COMPLETED" if version else "FAILED",
        solver_status=result.solver_status,
        objective_value=result.objective_value,
        metrics_json=result.metrics,
        started_at=started_at,
        finished_at=finished_at,
        error_summary="; ".join(result.infeasibility_reasons) if result.infeasibility_reasons else None,
    )
    db.add(run)
    db.flush()
    return version, run, validation
