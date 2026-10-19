from typing import Dict, Any, List
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import (
    ScheduleVersion, Assignment, Scenario, Resource, ResourceAvailability,
    Task, OptimisationRun, User
)
from app.core.permissions import UserRole
from app.core.errors import NotFoundError, ValidationError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.services.conflict_service import check_schedule_conflicts
from app.services.weather_impact import solver_weather_kwargs
from app.services.ops_constraints import combine_with_weather, solver_ops_kwargs
from app.engine.solver import solve_schedule_scenario
from app.services.proposal_service import load_solver_inputs, persist_proposal
from app.schemas.all_schemas import (
    OptimisationRunRequest, OptimisationRunResponse, ScheduleComparison
)

router = APIRouter(tags=["Optimisation"])


def generate_advisory_explanation(
    baseline_asns: List[Assignment],
    proposed_asns: List[Dict[str, Any]],
    tasks_map: Dict[str, Task],
    resources_map: Dict[str, Resource],
    unassigned_ids: List[str]
) -> str:
    """Deterministic, rule-based explanation grounded strictly in verifiable facts."""
    reassigned_count = 0
    time_shifted_count = 0

    base_map = {a.task_id: a for a in baseline_asns}

    for p in proposed_asns:
        t_id = p["task_id"]
        if t_id in base_map:
            b = base_map[t_id]
            if b.resource_id != p["resource_id"]:
                reassigned_count += 1
            elif abs((b.start_at - p["start_at"]).total_seconds()) > 60:
                time_shifted_count += 1

    lines = [
        f"Optimisation completed: {len(proposed_asns)} tasks scheduled successfully."
    ]
    if reassigned_count > 0:
        lines.append(f"• {reassigned_count} tasks were re-allocated to alternate available resources to avoid bottlenecks.")
    if time_shifted_count > 0:
        lines.append(f"• {time_shifted_count} tasks were temporally adjusted within their permissible operational windows.")
    if unassigned_ids:
        unassigned_names = [tasks_map[tid].name for tid in unassigned_ids if tid in tasks_map]
        lines.append(f"• Warning: {len(unassigned_ids)} tasks could not be scheduled without constraint violations: {', '.join(unassigned_names[:3])}.")
    else:
        lines.append("• 100% of prioritized mission tasks were assigned conflict-free.")

    return "\n".join(lines)


@router.post("/schedules/{schedule_id}/optimisation-runs", response_model=OptimisationRunResponse)
def trigger_optimisation_run(
    schedule_id: str,
    payload: OptimisationRunRequest,
    include_weather: bool = Query(False, description="Incorporate weather constraints and alerts into optimization"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """
    Trigger Google OR-Tools CP-SAT solver to generate an optimal rescheduled proposal
    resolving any existing conflicts while minimizing churn from baseline.
    Optionally incorporates live/synthetic weather constraints (hard blackouts and warning penalties).
    """
    inputs = load_solver_inputs(db, schedule_id)
    scenario_id = inputs.baseline.scenario_id
    tasks = inputs.tasks
    resources = inputs.resources
    baseline_asns = inputs.baseline_assignments

    # Weather constraints processing if requested
    use_weather = include_weather or bool(payload.include_weather)
    weather_kwargs: Dict[str, Any] = {}
    weather_info: Dict[str, Any] = {}
    if use_weather:
        weather_kwargs, weather_info = solver_weather_kwargs(db, scenario_id, tasks)
    # Threats, airspace, crews and stores always apply: they are rules, not forecasts
    ops_kwargs, ops_info = solver_ops_kwargs(db, scenario_id, tasks, resources)

    # Pre-solve audit
    log_audit_event(
        db,
        action="OPTIMISATION_STARTED",
        entity_type="SCHEDULE_VERSION",
        entity_id=schedule_id,
        actor=current_user,
        metadata={"scenario_id": scenario_id, "include_weather": use_weather}
    )

    # Execute Solver
    start_time = datetime.now(timezone.utc)
    solver_result = solve_schedule_scenario(
        scenario=inputs.scenario,
        resources=resources,
        availabilities=inputs.availabilities,
        tasks=tasks,
        baseline_assignments=baseline_asns,
        time_limit_seconds=payload.solver_time_limit_seconds or 30,
        weight_unassigned=payload.weight_unassigned or 10000,
        weight_delay=payload.weight_delay or 5,
        weight_churn=payload.weight_churn or 50,
        weight_makespan=payload.weight_makespan or 1,
        **combine_with_weather(weather_kwargs, ops_kwargs),
    )
    finished_time = datetime.now(timezone.utc)

    if use_weather and solver_result.metrics:
        solver_result.metrics["weather_constraints"] = weather_info
    if solver_result.metrics:
        solver_result.metrics["operational_layers"] = ops_info

    new_version, run_record, validation_res = persist_proposal(
        db, inputs.baseline, solver_result, current_user, start_time, finished_time
    )
    new_version_id = new_version.id if new_version else None

    tasks_map = {t.id: t for t in tasks}
    resources_map = {r.id: r for r in resources}
    advisory_text = generate_advisory_explanation(
        baseline_asns, solver_result.assignments, tasks_map, resources_map, solver_result.unassigned_tasks
    )

    log_audit_event(
        db,
        action="OPTIMISATION_COMPLETED",
        entity_type="OPTIMISATION_RUN",
        entity_id=run_record.id,
        actor=current_user,
        metadata={
            "status": run_record.status,
            "solver_status": solver_result.solver_status,
            "objective_value": solver_result.objective_value,
            "new_schedule_version_id": new_version_id
        }
    )
    db.commit()

    return OptimisationRunResponse(
        id=run_record.id,
        schedule_version_id=schedule_id,
        new_schedule_version_id=new_version_id,
        status=run_record.status,
        solver_status=run_record.solver_status,
        objective_value=run_record.objective_value,
        metrics_json=run_record.metrics_json,
        started_at=run_record.started_at,
        finished_at=run_record.finished_at,
        error_summary=run_record.error_summary,
        validation=validation_res,
        advisory_explanation=advisory_text
    )


@router.get("/optimisation-runs/{run_id}", response_model=OptimisationRunResponse)
def get_optimisation_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get status and details of an optimisation run."""
    run = db.query(OptimisationRun).filter(OptimisationRun.id == run_id).first()
    if not run:
        raise NotFoundError("OptimisationRun", run_id)
    return _run_response(db, run)


@router.get("/schedules/{schedule_id}/optimisation-run", response_model=OptimisationRunResponse)
def get_run_for_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Latest optimisation run that produced this (proposed) schedule version. Needed to approve/reject it."""
    # A run's schedule_version_id holds the version it produced (see trigger_optimisation)
    run = (
        db.query(OptimisationRun)
        .filter(OptimisationRun.schedule_version_id == schedule_id)
        .order_by(OptimisationRun.started_at.desc())
        .first()
    )
    if not run:
        raise NotFoundError("OptimisationRun for schedule", schedule_id)
    return _run_response(db, run)


def _run_response(db: Session, run: OptimisationRun) -> OptimisationRunResponse:
    validation_res = None
    if run.schedule_version_id:
        validation_res = check_schedule_conflicts(db, run.schedule_version_id)

    return OptimisationRunResponse(
        id=run.id,
        schedule_version_id=run.schedule_version_id,
        new_schedule_version_id=run.schedule_version_id,
        status=run.status,
        solver_status=run.solver_status,
        objective_value=run.objective_value,
        metrics_json=run.metrics_json,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_summary=run.error_summary,
        validation=validation_res
    )


@router.get("/optimisation-runs/{run_id}/comparison", response_model=ScheduleComparison)
def compare_optimisation_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Compare baseline schedule against the generated proposal in an optimisation run."""
    run = db.query(OptimisationRun).filter(OptimisationRun.id == run_id).first()
    if not run:
        raise NotFoundError("OptimisationRun", run_id)

    proposed_schedule = db.query(ScheduleVersion).filter(ScheduleVersion.id == run.schedule_version_id).first()
    if not proposed_schedule:
        raise NotFoundError("Proposed ScheduleVersion", run.schedule_version_id)

    baseline_schedule = db.query(ScheduleVersion).filter(
        ScheduleVersion.id == proposed_schedule.parent_version_id
    ).first()

    if not baseline_schedule:
        # Fallback to the same version if parent is missing
        baseline_schedule = proposed_schedule

    # Assignments
    base_asns = db.query(Assignment).filter(Assignment.schedule_version_id == baseline_schedule.id).all()
    prop_asns = db.query(Assignment).filter(Assignment.schedule_version_id == proposed_schedule.id).all()

    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == proposed_schedule.scenario_id).all()}
    resources = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == proposed_schedule.scenario_id).all()}

    base_map = {a.task_id: a for a in base_asns}
    prop_map = {a.task_id: a for a in prop_asns}

    changes = []
    reassigned = 0
    time_shifted = 0
    total_delay_base = 0
    total_delay_prop = 0

    all_task_ids = set(base_map.keys()).union(set(prop_map.keys()))
    for tid in all_task_ids:
        t = tasks.get(tid)
        t_name = t.name if t else tid
        b_asn = base_map.get(tid)
        p_asn = prop_map.get(tid)

        if b_asn and t:
            delay_b = max(0, int((b_asn.start_at - t.earliest_start).total_seconds() / 60))
            total_delay_base += delay_b
        if p_asn and t:
            delay_p = max(0, int((p_asn.start_at - t.earliest_start).total_seconds() / 60))
            total_delay_prop += delay_p

        change_type = "UNCHANGED"
        detail = ""

        if b_asn and not p_asn:
            change_type = "DROPPED"
            detail = "Task could not be scheduled in proposal."
        elif not b_asn and p_asn:
            change_type = "NEWLY_ASSIGNED"
            r_p = resources.get(p_asn.resource_id)
            detail = f"Assigned to {r_p.name if r_p else p_asn.resource_id}."
        elif b_asn and p_asn:
            is_res_diff = b_asn.resource_id != p_asn.resource_id
            is_time_diff = abs((b_asn.start_at - p_asn.start_at).total_seconds()) > 60
            if is_res_diff:
                reassigned += 1
                change_type = "REASSIGNED"
                r_old = resources.get(b_asn.resource_id)
                r_new = resources.get(p_asn.resource_id)
                detail = f"Reassigned: {r_old.name if r_old else 'Old'} -> {r_new.name if r_new else 'New'}."
            elif is_time_diff:
                time_shifted += 1
                change_type = "TIME_SHIFTED"
                shift_mins = int((p_asn.start_at - b_asn.start_at).total_seconds() / 60)
                detail = f"Shifted by {shift_mins:+d} minutes."

        changes.append({
            "task_id": tid,
            "task_name": t_name,
            "change_type": change_type,
            "details": detail,
            "baseline_resource": resources[b_asn.resource_id].name if b_asn and b_asn.resource_id in resources else None,
            "proposed_resource": resources[p_asn.resource_id].name if p_asn and p_asn.resource_id in resources else None,
            "baseline_start": b_asn.start_at.isoformat() if b_asn else None,
            "proposed_start": p_asn.start_at.isoformat() if p_asn else None,
        })

    return ScheduleComparison(
        baseline_version_id=baseline_schedule.id,
        proposed_version_id=proposed_schedule.id,
        baseline_version_number=baseline_schedule.version_number,
        proposed_version_number=proposed_schedule.version_number,
        total_tasks=len(tasks),
        baseline_assigned=len(base_asns),
        proposed_assigned=len(prop_asns),
        tasks_reassigned=reassigned,
        tasks_time_shifted=time_shifted,
        total_delay_minutes_baseline=total_delay_base,
        total_delay_minutes_proposed=total_delay_prop,
        delay_change_minutes=total_delay_prop - total_delay_base,
        changes=changes
    )
