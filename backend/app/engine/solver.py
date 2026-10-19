import math
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
from ortools.sat.python import cp_model

from app.models.all_models import (
    Scenario, Resource, ResourceAvailability, Task, TaskRequirement, Assignment
)
from app.services.ops_constraints import carries, crew_can_fly, store_demand


class ScheduleSolverResult:
    def __init__(
        self,
        solver_status: str,
        objective_value: Optional[float],
        assignments: List[Dict[str, Any]],
        unassigned_tasks: List[str],
        execution_time_seconds: float,
        metrics: Dict[str, Any],
        infeasibility_reasons: List[str]
    ):
        self.solver_status = solver_status
        self.objective_value = objective_value
        self.assignments = assignments
        self.unassigned_tasks = unassigned_tasks
        self.execution_time_seconds = execution_time_seconds
        self.metrics = metrics
        self.infeasibility_reasons = infeasibility_reasons


def solve_schedule_scenario(
    scenario: Scenario,
    resources: List[Resource],
    availabilities: List[ResourceAvailability],
    tasks: List[Task],
    baseline_assignments: Optional[List[Assignment]] = None,
    time_limit_seconds: int = 30,
    weight_unassigned: int = 10000,
    weight_delay: int = 5,
    weight_churn: int = 50,
    weight_makespan: int = 1,
    weather_blackouts: Optional[List[Dict[str, Any]]] = None,
    weather_penalties: Optional[Dict[str, int]] = None,
    priority_weights: Optional[Dict[str, int]] = None,
    delay_by_priority: bool = False,
    num_workers: int = 4,
    task_hard_windows: Optional[Dict[str, List[Tuple[datetime, datetime]]]] = None,
    task_soft_windows: Optional[Dict[str, List[Tuple[datetime, datetime]]]] = None,
    weight_weather_soft: int = 400,
    pair_hard_windows: Optional[Dict[Tuple[str, str], List[Tuple[datetime, datetime]]]] = None,
    crews: Optional[List[Any]] = None,
    crew_busy: Optional[Dict[str, List[Tuple[datetime, datetime]]]] = None,
    store_stock: Optional[Dict[str, int]] = None,
    forbidden_pairs: Optional[set] = None,
) -> ScheduleSolverResult:
    """
    Mathematical Optimization Engine using Google OR-Tools CP-SAT.
    Discretizes time to integer minutes and enforces all operational hard constraints
    including synthetic weather disruption blackouts and weather delay penalties.

    Optional layers (each skipped when None):
      pair_hard_windows  (task, aircraft) windows, e.g. a SAM zone only protected aircraft may enter
      crews              every sortie also needs one crew current on the aircraft type, with rest
                         between sorties, a duty limit and an optional shift
      crew_busy          fixed crew commitments (sorties already flying) that the plan must respect
      store_stock        units of each store type; sorties that need stores use them up
      forbidden_pairs    (task, aircraft) pairs that may never be chosen, e.g. a site above the ceiling
    """
    model = cp_model.CpModel()

    # Time reference origin (T0): earliest task start
    if not tasks:
        return ScheduleSolverResult("FEASIBLE", 0.0, [], [], 0.0, {}, [])

    t0 = min(t.earliest_start for t in tasks)
    # Horizon max in minutes (e.g. up to 10 days)
    horizon_max_dt = max(t.latest_finish for t in tasks) + timedelta(days=2)
    max_horizon_minutes = int((horizon_max_dt - t0).total_seconds() / 60)

    def _like_t0(dt: datetime) -> datetime:
        # SQLite returns naive UTC datetimes; weather windows are tz-aware. Compare like with like.
        if t0.tzinfo is None and dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        if t0.tzinfo is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def to_min(dt: datetime) -> int:
        return max(0, int((_like_t0(dt) - t0).total_seconds() / 60))

    def to_min_up(dt: datetime) -> int:
        # The end of a closed period rounds up: a blackout ending at 1000:30 still blocks minute 1000
        return max(0, math.ceil((_like_t0(dt) - t0).total_seconds() / 60))

    def from_min(m: int) -> datetime:
        return t0 + timedelta(minutes=m)

    # Priority multipliers (callers may override, e.g. to favour critical missions harder)
    priority_weights = priority_weights or {
        "CRITICAL": 10,
        "HIGH": 5,
        "MEDIUM": 2,
        "LOW": 1
    }

    # Pre-compute qualification mapping
    resource_quals: Dict[str, set] = {}
    for r in resources:
        meta = r.metadata_json or {}
        resource_quals[r.id] = set(meta.get("qualifications", []))

    # Identify eligible resources per task
    task_eligible_resources: Dict[str, List[Resource]] = {}
    task_stores: Dict[str, Dict[str, int]] = {t.id: store_demand(t) for t in tasks}
    for t in tasks:
        req_quals = [req.requirement_value for req in t.requirements if req.requirement_type == "QUALIFICATION"]
        eligible = []
        for r in resources:
            if r.status in ["GROUNDED", "UNAVAILABLE"]:
                continue
            if not all(q in resource_quals[r.id] for q in req_quals):
                continue
            # The aircraft must be able to carry every store the task needs
            if not all(carries(r, kind) for kind in task_stores[t.id]):
                continue
            if forbidden_pairs and (t.id, r.id) in forbidden_pairs:
                continue
            eligible.append(r)
        task_eligible_resources[t.id] = eligible

    # Baseline map for churn minimization: (task_id, resource_id) -> 1
    baseline_map: Dict[Tuple[str, str], int] = {}
    if baseline_assignments:
        for ba in baseline_assignments:
            baseline_map[(ba.task_id, ba.resource_id)] = 1

    # Decision variables
    # x[t_id, r_id]: Bool indicating task t assigned to resource r
    x: Dict[Tuple[str, str], cp_model.IntVar] = {}
    # intervals[r_id]: list of interval vars for resource r
    res_intervals: Dict[str, List[cp_model.IntervalVar]] = {r.id: [] for r in resources}
    # task_start[t_id]: start minute of task t
    task_start: Dict[str, cp_model.IntVar] = {}
    # task_end[t_id]: end minute of task t
    task_end: Dict[str, cp_model.IntVar] = {}
    # task_is_assigned[t_id]: bool indicating task is scheduled
    task_is_assigned: Dict[str, cp_model.IntVar] = {}

    for t in tasks:
        e_start_min = to_min(t.earliest_start)
        l_finish_min = to_min(t.latest_finish)
        dur = max(1, t.duration_minutes)

        t_start = model.NewIntVar(e_start_min, l_finish_min - dur, f"start_{t.id[:8]}")
        t_end = model.NewIntVar(e_start_min + dur, l_finish_min, f"end_{t.id[:8]}")
        model.Add(t_end == t_start + dur)

        task_start[t.id] = t_start
        task_end[t.id] = t_end

        assigned_literals = []
        for r in task_eligible_resources[t.id]:
            pair_key = (t.id, r.id)
            pair_var = model.NewBoolVar(f"x_{t.id[:6]}_{r.id[:6]}")
            x[pair_key] = pair_var
            assigned_literals.append(pair_var)

            # Optional interval for resource r
            opt_interval = model.NewOptionalIntervalVar(
                t_start, dur, t_end, pair_var, f"interval_{t.id[:6]}_{r.id[:6]}"
            )
            res_intervals[r.id].append(opt_interval)

        # Assignment indicator (at most 1 resource per task)
        is_assigned = model.NewBoolVar(f"assigned_{t.id[:8]}")
        task_is_assigned[t.id] = is_assigned
        if assigned_literals:
            model.Add(sum(assigned_literals) == is_assigned)
        else:
            model.Add(is_assigned == 0)

    # 2. Resource Blackout / Maintenance Windows
    # If a resource has an unavailable window [b_start, b_end], no task interval on that resource may intersect it
    def _fixed_block(start: datetime, end: datetime, name: str) -> Optional[cp_model.IntervalVar]:
        # Windows are clipped to the planning horizon. One that ended before it is dropped:
        # clipping both ends to 0 would otherwise create an impossible interval (size 1, end 0).
        b_s, b_e = to_min(start), to_min_up(end)
        if b_e <= b_s:
            return None
        return model.NewIntervalVar(b_s, b_e - b_s, b_e, name)

    for a in availabilities:
        if not a.available and a.resource_id in res_intervals:
            bo_interval = _fixed_block(a.start_at, a.end_at, f"blackout_{a.id[:8]}")
            if bo_interval is not None:
                res_intervals[a.resource_id].append(bo_interval)

    # 3. Weather Disruption Blackout Windows
    if weather_blackouts:
        for idx, wb in enumerate(weather_blackouts):
            rid = wb.get("resource_id")
            if rid and rid in res_intervals:
                wb_interval = _fixed_block(wb["start_at"], wb["end_at"], f"weather_bo_{idx}_{rid[:6]}")
                if wb_interval is not None:
                    res_intervals[rid].append(wb_interval)

    # 1. Non-overlap per resource. Added only after maintenance and weather blackouts have been
    # appended above: AddNoOverlap copies the list, so intervals added later would be ignored.
    for r in resources:
        if res_intervals[r.id]:
            model.AddNoOverlap(res_intervals[r.id])

    # 1b. Crews: one per sortie, current on the aircraft type, rested, within duty and shift
    y: Dict[Tuple[str, str], cp_model.IntVar] = {}
    if crews is not None:
        crew_intervals: Dict[str, List[cp_model.IntervalVar]] = {c.id: [] for c in crews}
        for c in crews:
            for idx, (bs, be) in enumerate((crew_busy or {}).get(c.id, [])):
                block = _fixed_block(bs, be + timedelta(minutes=c.min_rest_minutes), f"crew_busy_{c.id[:6]}_{idx}")
                if block is not None:
                    crew_intervals[c.id].append(block)
        for t in tasks:
            dur = max(1, t.duration_minutes)
            lits = []
            for c in crews:
                compatible = [x[(t.id, r.id)] for r in task_eligible_resources[t.id] if crew_can_fly(c, r.resource_type)]
                if not compatible or c.max_duty_minutes - c.duty_used_minutes < dur:
                    continue
                if c.duty_end is not None and to_min(c.duty_end) < to_min(t.earliest_start) + dur:
                    continue
                if c.duty_start is not None and to_min(c.duty_start) > to_min(t.latest_finish) - dur:
                    continue
                var = model.NewBoolVar(f"crew_{t.id[:6]}_{c.id[:6]}")
                y[(t.id, c.id)] = var
                model.Add(var <= sum(compatible))
                # The crew is busy for the sortie plus its minimum rest afterwards
                rest_end = model.NewIntVar(0, max_horizon_minutes + c.min_rest_minutes, f"crew_end_{t.id[:6]}_{c.id[:6]}")
                model.Add(rest_end == task_start[t.id] + dur + c.min_rest_minutes)
                crew_intervals[c.id].append(model.NewOptionalIntervalVar(
                    task_start[t.id], dur + c.min_rest_minutes, rest_end, var, f"crew_iv_{t.id[:6]}_{c.id[:6]}"
                ))
                if c.duty_start is not None:
                    model.Add(task_start[t.id] >= to_min_up(c.duty_start)).OnlyEnforceIf(var)
                if c.duty_end is not None:
                    model.Add(task_end[t.id] <= to_min(c.duty_end)).OnlyEnforceIf(var)
                lits.append(var)
            if lits:
                model.Add(sum(lits) == task_is_assigned[t.id])
            else:
                model.Add(task_is_assigned[t.id] == 0)
        for c in crews:
            if crew_intervals[c.id]:
                model.AddNoOverlap(crew_intervals[c.id])
            flown = [max(1, t.duration_minutes) * y[(t.id, c.id)] for t in tasks if (t.id, c.id) in y]
            if flown:
                model.Add(sum(flown) <= c.max_duty_minutes - c.duty_used_minutes)

    # 1c. Stores: sorties that need a store use it up; the plan cannot use more than is held
    if store_stock is not None:
        for kind, held in store_stock.items():
            users = [(task_stores[t.id][kind], task_is_assigned[t.id]) for t in tasks if kind in task_stores[t.id]]
            if users:
                model.Add(sum(q * v for q, v in users) <= max(0, held))

    # 4. Per-task weather windows (site-specific forecast limits)
    # An assigned task must finish before the window opens or start after it closes.
    def _outside(t_id: str, w_start: datetime, w_end: datetime, tag: str) -> List[cp_model.IntVar]:
        a, b = to_min(w_start), to_min_up(w_end)
        before = model.NewBoolVar(f"wx_{tag}_before_{t_id[:6]}_{a}")
        after = model.NewBoolVar(f"wx_{tag}_after_{t_id[:6]}_{a}")
        model.Add(task_end[t_id] <= a).OnlyEnforceIf(before)
        model.Add(task_start[t_id] >= b).OnlyEnforceIf(after)
        return [before, after]

    weather_soft_terms = []
    # Zones that only some aircraft may enter: that pair may not overlap the window
    for (t_id, r_id), windows in (pair_hard_windows or {}).items():
        if (t_id, r_id) not in x:
            continue
        for ws, we in windows:
            model.AddBoolOr(_outside(t_id, ws, we, "pair") + [x[(t_id, r_id)].Not()])
    for t_id, windows in (task_hard_windows or {}).items():
        if t_id not in task_is_assigned:
            continue
        for ws, we in windows:
            model.AddBoolOr(_outside(t_id, ws, we, "hard") + [task_is_assigned[t_id].Not()])
    for t_id, windows in (task_soft_windows or {}).items():
        if t_id not in task_is_assigned:
            continue
        for ws, we in windows:
            inside = model.NewBoolVar(f"wx_soft_in_{t_id[:6]}_{to_min(ws)}")
            model.AddBoolOr(_outside(t_id, ws, we, "soft") + [inside, task_is_assigned[t_id].Not()])
            weather_soft_terms.append(inside)

    # Objective Terms
    objective_terms = []
    for inside in weather_soft_terms:
        objective_terms.append(inside * weight_weather_soft)

    # Term A: Penalize Unassigned Tasks (heavily weighted by priority)
    for t in tasks:
        prio_w = priority_weights.get(t.priority, 1)
        unassigned_var = model.NewBoolVar(f"unassigned_{t.id[:8]}")
        model.Add(unassigned_var == 1 - task_is_assigned[t.id])
        objective_terms.append(unassigned_var * (weight_unassigned * prio_w))

    # Term B: Minimize Departure Delays from earliest_start
    for t in tasks:
        e_start_min = to_min(t.earliest_start)
        delay_var = model.NewIntVar(0, max_horizon_minutes, f"delay_{t.id[:8]}")
        model.Add(delay_var == task_start[t.id] - e_start_min)
        delay_w = weight_delay * (priority_weights.get(t.priority, 1) if delay_by_priority else 1)
        objective_terms.append(delay_var * delay_w)

    # Term C: Minimize Schedule Churn (modifications from baseline)
    for (t_id, r_id), var in x.items():
        was_in_baseline = baseline_map.get((t_id, r_id), 0)
        churn_var = model.NewBoolVar(f"churn_{t_id[:6]}_{r_id[:6]}")
        if was_in_baseline == 1:
            # churn if dropped
            model.Add(churn_var == 1 - var)
        else:
            # churn if newly added
            model.Add(churn_var == var)
        objective_terms.append(churn_var * weight_churn)

    # Term D: Makespan Minimization
    makespan = model.NewIntVar(0, max_horizon_minutes, "makespan")
    for t in tasks:
        model.Add(makespan >= task_end[t.id])
    objective_terms.append(makespan * weight_makespan)

    # Term E: Weather Soft Constraints (discourage scheduling during weather warning alerts)
    if weather_penalties:
        for t in tasks:
            if t.id in weather_penalties and weather_penalties[t.id] > 0:
                p_cost = weather_penalties[t.id]
                objective_terms.append(task_is_assigned[t.id] * p_cost)

    model.Minimize(sum(objective_terms))

    # Configure and solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = num_workers

    status_code = solver.Solve(model)
    exec_time = solver.WallTime()

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "INVALID",
        cp_model.UNKNOWN: "UNKNOWN"
    }
    solver_status = status_map.get(status_code, "UNKNOWN")

    assignments_out: List[Dict[str, Any]] = []
    unassigned_out: List[str] = []
    infeasibility_reasons: List[str] = []

    if solver_status in ["OPTIMAL", "FEASIBLE"]:
        for t in tasks:
            assigned = solver.Value(task_is_assigned[t.id])
            if assigned == 1:
                start_m = solver.Value(task_start[t.id])
                end_m = solver.Value(task_end[t.id])
                # Find chosen resource
                chosen_res_id = None
                for r in task_eligible_resources[t.id]:
                    if solver.Value(x[(t.id, r.id)]) == 1:
                        chosen_res_id = r.id
                        break

                chosen_crew_id = next(
                    (c.id for c in (crews or []) if (t.id, c.id) in y and solver.Value(y[(t.id, c.id)]) == 1), None
                )
                if chosen_res_id:
                    assignments_out.append({
                        "task_id": t.id,
                        "resource_id": chosen_res_id,
                        "crew_id": chosen_crew_id,
                        "start_at": from_min(start_m),
                        "end_at": from_min(end_m)
                    })
            else:
                unassigned_out.append(t.id)

    elif solver_status == "INFEASIBLE":
        # Identify impossible tasks
        for t in tasks:
            if not task_eligible_resources[t.id]:
                infeasibility_reasons.append(
                    f"Task '{t.name}' has no qualified, active resources available."
                )

    metrics = {
        "execution_time_seconds": round(exec_time, 3),
        "total_tasks": len(tasks),
        "assigned_tasks": len(assignments_out),
        "unassigned_tasks": len(unassigned_out),
        "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts()
    }

    return ScheduleSolverResult(
        solver_status=solver_status,
        objective_value=solver.ObjectiveValue() if solver_status in ["OPTIMAL", "FEASIBLE"] else None,
        assignments=assignments_out,
        unassigned_tasks=unassigned_out,
        execution_time_seconds=exec_time,
        metrics=metrics,
        infeasibility_reasons=infeasibility_reasons
    )
