# Implementation Plan (IMPLEMENTATION_PLAN.md)
## Secure AI-Assisted Scheduling and Dynamic Rescheduling Decision-Support System (PS 26250)

---

### Overview & Roadmap

This plan establishes the execution sequence to deliver a working full-stack decision-support prototype. Every phase has clear deliverables, automated testing milestones, and verifiable exit criteria.

---

### Phase Breakdown

#### PHASE 1 — Inspect and Plan (Current)
- [x] Inspect repository file structure and host prerequisites.
- [x] Document environment constraints (empty workspace, Windows host, shell environment requirements).
- [x] Create `ARCHITECTURE.md` defining system topology, ER models, CP-SAT formulation, independent validator, and RBAC matrix.
- [x] Create `IMPLEMENTATION_PLAN.md` with tasks, dependencies, and definitions of done.
- **Definition of Done**: Architecture and roadmap documented; environment prerequisites identified.

#### PHASE 2 — Foundation Setup (Backend, Database, Frontend Boilerplate)
- **Backend Setup**:
  - Directory structure: `backend/app/` with `core/`, `api/`, `models/`, `schemas/`, `repositories/`, `services/`, `engine/`, `simulation/`, `db/`.
  - Core settings & configuration (`config.py` using `pydantic-settings`).
  - Database engine setup: PostgreSQL connection pooling with fallback SQLite support for lightweight isolated test execution (`session.py`, `base.py`).
  - Health check endpoint (`GET /health`).
  - Database schema models via SQLAlchemy 2.0: `User`, `Scenario`, `Resource`, `ResourceAvailability`, `Task`, `TaskRequirement`, `ScheduleVersion`, `Assignment`, `Disruption`, `OptimisationRun`, `Approval`, `AuditEvent`.
  - Deterministic database seed script generating realistic fictional operational data (12 resources, 24 tasks, operational windows, initial scenario, 4 test users for ADMIN, PLANNER, REVIEWER, VIEWER).
- **Frontend Setup**:
  - Directory structure: `frontend/src/` with `api/`, `components/`, `features/`, `hooks/`, `types/`, `utils/`.
  - Configuration: `package.json`, `tsconfig.json`, `vite.config.ts`, `tailwind.config.js`, `postcss.config.js`.
  - Base styling: `index.css` with dark mode theme, CSS design tokens, smooth typography, and responsive grid layouts.
  - Core layout: `AppLayout.tsx`, `Sidebar.tsx`, `Header.tsx`, `StatusBadge.tsx`, `LoadingState.tsx`, `ErrorState.tsx`, `EmptyState.tsx`, `ConfirmDialog.tsx`.
- **Infrastructure**:
  - `infra/Dockerfile.backend`, `infra/Dockerfile.frontend`, `infra/docker-compose.yml`, `.env.example`, `.gitignore`.
- **Definition of Done**: Backend boots with `/health`, database initializes and seeds, frontend builds cleanly with core layout and navigation shell.

#### PHASE 3 — Core Data, Authentication & API Endpoints
- **Authentication & RBAC**:
  - JWT token generation, password hashing (argon2 / bcrypt).
  - Endpoints: `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`.
  - Role-based authorization dependencies (`require_roles("ADMIN", "PLANNER")`).
- **Entity Management Endpoints**:
  - Scenarios: `GET /api/v1/scenarios`, `POST /api/v1/scenarios`, `GET /api/v1/scenarios/{id}`, `PATCH /api/v1/scenarios/{id}`, `POST /api/v1/scenarios/{id}/generate-data`.
  - Resources: `GET /api/v1/resources`, `POST /api/v1/resources`, `GET /api/v1/resources/{id}`, `PATCH /api/v1/resources/{id}`, `DELETE /api/v1/resources/{id}`.
  - Tasks: `GET /api/v1/tasks`, `POST /api/v1/tasks`, `GET /api/v1/tasks/{id}`, `PATCH /api/v1/tasks/{id}`, `DELETE /api/v1/tasks/{id}`.
- **Frontend Views**:
  - `LoginPage.tsx`: Clean, intuitive authentication with pre-filled demo role switcher.
  - `ScenarioListPage.tsx` & `ScenarioDetailPage.tsx`: Scenario overview, data generation, and parameter editing.
  - `ResourceManagementPage.tsx`: Resource inventory, availability windows, qualifications, and live filter/search.
  - `TaskManagementPage.tsx`: Task backlog, priority levels, duration, time windows, and requirement tags.
- **Definition of Done**: Full CRUD on Scenarios, Resources, and Tasks with RBAC security; interactive frontend tables and forms connected to live API endpoints.

#### PHASE 4 — Scheduling, Independent Validator & OR-Tools CP-SAT
- **Baseline Schedule Construction**:
  - `schedule_service.py`: Generates initial schedule version `v1` assigning tasks to eligible resources within valid time horizons.
  - `Assignment` persistence linking tasks, resources, and time windows.
- **Independent Conflict Detection Engine**:
  - `conflict_service.py`: Pure deterministic rule engine evaluating 5 hard constraints (overlaps, availability blackout violations, time window limits, eligibility mismatches, duplicate assignments).
  - Diagnostic response returning human-readable explanation and exact conflict interval.
- **OR-Tools CP-SAT Optimisation Engine**:
  - `solver.py`: Formulates the discrete-time scheduling model using interval variables and boolean indicators.
  - Objective: Weighted multi-criteria optimization minimizing unassigned penalty, schedule delays, resource churn, and total makespan.
  - Status handling: OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN.
  - Post-solve pipeline: Every CP-SAT solution is automatically passed through the independent conflict validator before being committed as a candidate.
- **Frontend Views**:
  - `SchedulePage.tsx` & `ScheduleTimeline.tsx`: Interactive Gantt-style timeline showing resources on Y-axis, time on X-axis, assigned task blocks, availability blocks, and conflict highlights.
  - `ConflictPanel.tsx`: Clear diagnostic cards detailing detected violations with severity badges and affected task references.
- **Definition of Done**: Baseline schedule generation works; independent validator catches injected conflicts; OR-Tools CP-SAT engine produces optimal/feasible schedules or explains infeasibility; timeline displays assignments and conflicts accurately.

#### PHASE 5 — Synthetic Disruptions, Versioning & Review Workflow
- **Synthetic Disruption Simulator**:
  - `disruptions.py` & `simulation/generator.py`: Generates deterministic disruptions (Resource Grounded, Window Shift, Duration Surge, Deadline Tightening, Capacity Drop).
  - `POST /api/v1/scenarios/{id}/disruptions`: Applies disruption, flags invalidated assignments, creates conflict report.
- **Schedule Version DAG & Immutability**:
  - Creates child `ScheduleVersion` linked to parent version.
  - Approved versions are locked as immutable (`status = "APPROVED"`).
- **Comparison & Re-plan Workflow**:
  - `ComparisonView.tsx`: Side-by-side delta between baseline and proposed schedule (task shifts, resource reallocations, unassigned tasks, delay delta).
  - `OptimisationRunPanel.tsx`: Live solver status, execution runtime, objective value, and validation status.
- **Human-in-the-Loop Approval**:
  - `ReviewPage.tsx`: Allows users with `REVIEWER` or `ADMIN` roles to review comparison and validation report, then approve or reject with a mandatory audit reason.
  - Stale approval rejection: Rejects approval if the parent schedule was modified concurrently.
- **Definition of Done**: End-to-end disruption-to-replan loop functioning; side-by-side diff clearly highlights changes; approval updates version state and preserves immutability.

#### PHASE 6 — Security, Audit Ledger & Reporting
- **Audit System**:
  - `audit_service.py` & `GET /api/v1/audit-events`: Records all state mutations (auth events, scenario creation, disruption application, solver runs, approvals/rejections).
  - Scrubbing logic ensures zero secret/credential leakage.
- **Advisory AI & Rule-based Explanations**:
  - `ExplanationProvider`: Synthesizes disruption impact and re-allocation rationale into structured advisory text.
- **Reporting & KPIs**:
  - `ReportsPage.tsx` & `DashboardPage.tsx`: Computes real metrics from persistent data (Resource Utilization %, On-Time Task %, Churn Rate, Average Delay, Conflict Count).
  - CSV export for verified schedule audit trails.
- **Definition of Done**: Audit logs recorded on all mutations; RBAC tests confirm unauthorized actions are blocked with `403 Forbidden`; dashboard KPIs reflect live database figures.

#### PHASE 7 — Comprehensive Testing, Demo Walkthrough & Final Documentation
- **Test Suite**:
  - Unit tests: Constraint satisfaction, conflict detector edge cases, multi-criteria weights.
  - API & Security tests: Authentication, RBAC access denial, version conflict rejection.
  - End-to-End integration test covering the complete 15-step acceptance scenario.
- **Documentation**:
  - `README.md` with complete setup instructions, Docker Compose execution, demo walkthrough steps, and API endpoint catalogue.
- **Definition of Done**: All automated tests pass; full 15-step demonstration scenario runs flawlessly; comprehensive documentation delivered.

---

### Verification Matrix & Test Strategy

| Test Suite | Target | Test Cases |
| :--- | :--- | :--- |
| **Unit - Constraints** | `engine/constraints.py`, `conflict_service.py` | Overlap detection, availability blackout, time window violations, qualification mismatches, double bookings. |
| **Unit - Solver** | `engine/solver.py` | Optimal resolution, feasible resolution, infeasible scenario explanation, multi-criteria priority weights. |
| **API & Auth** | `api/v1/endpoints/auth.py`, `deps.py` | Valid login, invalid password, expired token, role permission enforcement (403 Forbidden). |
| **API - Business Logic** | `api/v1/endpoints/*` | Scenario isolation, immutable schedule version locking, stale approval rejection (409 Conflict). |
| **End-to-End** | Full System Workflow | 15-step complete loop: Login -> Create Scenario -> Seed Data -> Baseline -> Disruption -> Conflict -> Re-solve -> Validate -> Compare -> Review -> Approve -> Audit. |
