# Secure AI-Assisted Scheduling and Dynamic Rescheduling Decision-Support System
### SIH 2026 — Problem Statement 26250 (AirOps Scheduler)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-4285F4?logo=google&logoColor=white)](https://developers.google.com/optimization)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-3.4-38B2AC?logo=tailwind-css&logoColor=white)](https://tailwindcss.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Security RBAC](https://img.shields.io/badge/Security-RBAC%20%2B%20Audit-emerald)](#security--rbac-matrix)

---

## 1. Project Overview

**AirOps Scheduler (PS 26250)** is an enterprise decision-support prototype engineered to manage complex resource scheduling, simulate dynamic operational disruptions, detect cascading constraint violations, and generate mathematically validated reschedule proposals.

When disruptions occur (e.g. aircraft grounded, runway maintenance blackouts, weather transit surges, or tightened casualty evacuation deadlines), the system:
1. Maintains unified data representations across resources, tasks, availability windows, and qualification matrices.
2. Identifies and isolates conflicting assignments using an independent deterministic multi-rule validator.
3. Reschedules missions using **Google OR-Tools CP-SAT (Constraint Programming with Satisfiability)** to minimize schedule churn, unassigned tasks, and departure delays.
4. Provides side-by-side delta comparisons and fact-grounded advisory explanations.
5. Imposes human-in-the-loop authorization gates, preventing unapproved schedule activation while capturing tamper-evident audit logs.

> ### Operational Safety Boundary
> This prototype is designed strictly for educational and demonstration purposes. It uses fictional resources, synthetic datasets, and generic scheduling constraints. It has **no** connectivity to classified military networks, operational tactical feeds, weapons, or real-world targeting systems.

---

## 2. System Architecture

The solution uses a **modular monolith** with clean architectural separation:

```
React 18 Frontend (Vite + TypeScript + Tailwind CSS)
       |
       |  HTTPS / REST JSON (OpenAPI v3)
       v
FastAPI Application Layer (Python 3.11+)
       |
       +--> Authentication & RBAC Gatekeeper (JWT / Argon2)
       +--> Scenario, Resource & Task Services
       +--> Independent Conflict Detector (Pure-Python 5-Rule Engine)
       +--> Optimisation Engine (Google OR-Tools CP-SAT)
       +--> Synthetic Disruption Simulator
       +--> Advisory Explanation Provider (Fact-Grounded)
       +--> Human Review & Approval Workflow
       +--> Immutable Security Audit Ledger
       |
       v
PostgreSQL / SQLite Database
```

---

## 3. Security & RBAC Matrix

| Role | Scenarios | Tasks & Resources | Disruptions | CP-SAT Optimiser | Review & Approve | Audit Ledger |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **ADMIN** | Full | Full | Full | Execute | Approve / Reject | Full Access |
| **PLANNER** | Full | Full | Create / Apply | Execute | View Proposal | View Scenarios |
| **REVIEWER** | Read-Only | Read-Only | Read-Only | Read-Only | Approve / Reject | Full Access |
| **VIEWER** | Read-Only | Read-Only | Read-Only | Read-Only | Read-Only | Denied |

* **Immutable Versioning:** Approved schedules (`status = "APPROVED"`) are locked and cannot be edited. Concurrent approvals or modifications reject stale parents with `409 Conflict`.
* **Zero-Secret Audit Logging:** All system state mutations record caller ID, action, entity UUID, and metadata without recording passwords or JWT credentials.

---

## 4. Prerequisites

- **Python**: 3.10 or 3.11+
- **Node.js**: 18.x or 20.x+ (`npm` package manager)
- **Database**: PostgreSQL 15+ or local SQLite fallback
- **Docker & Docker Compose** (Optional for containerized run)

---

## 5. Local Setup & Quickstart

### Step 1: Clone and Configure Environment

```bash
git clone <repo-url> air-ops-scheduler
cd air-ops-scheduler

# Copy environment template
cp .env.example .env
```

### Step 2: Backend Setup & Seed Data

```bash
cd backend

# Create virtual environment
python -m venv .venv
# Activate on Windows:
.venv\Scripts\activate
# Activate on Linux/macOS:
source .venv/bin/activate

# Install dependencies (add [dev] for the test tools)
pip install -e ".[dev]"

# Apply database migrations, then seed the demo dataset
# (the server also does both on startup, so these are optional)
alembic upgrade head
python app/db/seed.py

# Launch FastAPI backend server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Schema changes** go through Alembic. After editing a model in `app/models/`:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Databases created before migrations existed are detected on startup and stamped at the baseline revision automatically.

**Live weather** comes from two free, keyless public APIs: hourly forecasts from [Open-Meteo](https://open-meteo.com) (one batched request for all sites, cached 15 min) and the nearest airport's METAR/TAF from the [NOAA Aviation Weather Center](https://aviationweather.gov/data/api/).

* Backend OpenAPI documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
* Health check: [http://localhost:8000/health](http://localhost:8000/health)

### Step 3: Frontend Setup

```bash
# In a new terminal:
cd frontend

# Install frontend dependencies
npm install

# Start Vite dev server
npm run dev
```

* Frontend application: [http://localhost:5173](http://localhost:5173)

---

### Demo features

* **Live exercise** (`/exercise`): plays "Exercise WINTER LIFT" on a fast clock against a copy of the contested scenario. Scripted events (aircraft unserviceable, gust warning, new casualty evacuation, headwinds, tighter deadline) land unannounced; after each, the system re-checks the active plan and generates courses of action in the background from the simulated "now" (sorties already airborne stay fixed). A planner adopts a plan, a reviewer or admin approves it. The after-action summary compares the untouched original plan with the plan in force. Simulated weather is labelled "exercise inject" and never mixed into live forecasts. Sign in as **admin** to adopt and approve in one session.
* **Courses of action** (`/courses-of-action`): solves the same situation under four intents (fastest, least disruption, weather-safe, critical first), validates each plan independently, flags identical plans, and suggests one by an explicit rule. Adopting creates a proposal for review; nothing activates without approval.
* **Object explorer** (`/explorer`): every aircraft, task, site and capability as a linked object, with a layered link graph (capability → aircraft → task → site). Each object has a profile with its links, unavailability, conflicts, disruptions and audit history; single points of failure (a capability held by one aircraft) are flagged.
* **Ops map** (`/ops-map`): the active plan on a terrain map with a time slider and play control: aircraft move along their sorties and sites change colour with the forecast for that hour. Sorties are drawn as round trips from the logistics hub because aircraft bases are not modelled.
* **Data import** (`/import`): aircraft, tasks, maintenance windows and sites from CSV or Excel. Headers are matched loosely, every row is validated in a preview, and nothing is saved until all rows pass. Templates are downloadable.
* **Alerts** (`/alerts`, bell in the header): editable rules (task without aircraft, late start, sortie in critical weather, rule conflicts, aircraft flying hours, single-source capability) evaluated on the active plan; each alert opens the object it concerns.
* **Branches** (Scenarios page → Branch, then `/compare`): copy a scenario to try changes, then compare it with its parent measure by measure and task by task.
* **Copilot** (header button): answers questions about a scenario using read-only tools (situation, weather, tasks, "why is this task here", and a what-if that is rolled back). It cannot change a plan. Needs `ANTHROPIC_API_KEY` in `backend/.env`; without it the panel says so and the rest of the app works.

---

## 6. Docker Compose Deployment

Run the complete multi-tier stack (PostgreSQL + FastAPI + React + Nginx) with one command:

```bash
cd infra
docker-compose up --build -d
```

* Frontend: [http://localhost:3000](http://localhost:3000)
* Backend API: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 7. Demo Accounts & Seed Data

| Role | Email | Password | Primary Capabilities |
| :--- | :--- | :--- | :--- |
| **PLANNER** | `planner@airops.demo` | `PlannerPass123!` | Create scenarios, inject disruptions, run CP-SAT solver |
| **REVIEWER** | `reviewer@airops.demo` | `ReviewerPass123!` | Audit comparison deltas, approve or reject proposals |
| **ADMIN** | `admin@airops.demo` | `AdminPass123!` | Full administrative configuration and system audits |
| **VIEWER** | `viewer@airops.demo` | `ViewerPass123!` | Read-only observation across all dashboards |

*(The header has a persona switcher for demonstration, a light/dark toggle and a print button.)*

---

## 8. Automated Test Suite Execution

Run all unit, API, constraint, and end-to-end acceptance tests:

```bash
cd backend
pytest tests/ -v
```

Tests use an in-memory SQLite database and mock both weather providers, so they run offline and never touch `scheduler.db`.

### Test Coverage Highlights:
- **Unit Constraints (`tests/unit/test_conflict_engine.py`)**: Tests overlap detection, availability blackouts, strict deadline bounds, and qualification mismatches.
- **Unit Solver (`tests/unit/test_solver.py`)**: Verifies CP-SAT mathematical correctness, priority weighting, and infeasibility reporting.
- **End-to-End Acceptance (`tests/api/test_api_endpoints.py`)**: Executes the 15-step scenario required by the problem statement.

---

## 9. 15-Step Demonstration Scenario Walkthrough

Follow this sequence to demonstrate the complete workflow:

1. **Login**: Sign in as `planner@airops.demo`.
2. **Dashboard**: Observe real-time KPIs (Total Tasks, Assigned Sorties, Active Conflicts).
3. **Scenario Inspection**: Navigate to **Scenarios** to review the *"Northern Corridor Relief & Air Supply Op"*.
4. **Resources & Tasks**: Inspect the fleet (C-130, IL-76, Mi-17, ALH-Dhruv) and mission backlog.
5. **Baseline Schedule**: Open **Schedule Timeline** to view the conflict-free Gantt timeline (Schedule v1).
6. **Constraint Validation**: Click **Validate**; confirm 0 conflicts detected.
7. **Disruption Studio**: Open **Disruption Studio**; select **"Ground Heavy Aircraft (C-130-Alpha)"** and click **Inject Disruption**.
8. **Conflict Alerts**: Observe the generated conflict card: *`RESOURCE_UNAVAILABLE: Resource 'C-130-Alpha' is currently GROUNDED but assigned to 4 sorties.`*
9. **Launch Optimiser**: Open **Optimisation & Diff**; tune multi-criteria weights and click **Launch Optimisation Solver**.
10. **Solver Proof**: Verify that OR-Tools CP-SAT finds an optimal/feasible candidate in $<0.5$ seconds, generating child version `v2`.
11. **Independent Verification**: Confirm that the independent validator passes candidate `v2` with 100% compliance.
12. **Delta Comparison**: Switch to the **Side-by-Side Comparison** tab to inspect how missions on the grounded C-130-Alpha were transferred to C-130-Bravo and IL-76.
13. **Role Switch to Reviewer**: Click the persona switcher in the top-right header and select **REVIEWER**.
14. **Human Review & Approval**: Open **Review & Approval**, enter justification (*"Re-allocations verified conflict-free and compliant"*), and click **Approve & Activate**.
15. **Immutability & Audit**: Verify Schedule `v2` is now `APPROVED` and previous versions are `SUPERSEDED`. Open **Audit Ledger** to confirm the immutable `PROPOSAL_APPROVED` event.

---

## 10. Repository Directory Layout

```
air-ops-scheduler/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI bootstrap & lifespan
│   │   ├── core/                    # Config, Security, RBAC Permissions, Errors
│   │   ├── db/                      # Base, Sessionmaker & Deterministic Seeder
│   │   ├── models/                  # SQLAlchemy 2.0 ORM domain entities
│   │   ├── schemas/                 # Pydantic v2 validation contracts
│   │   ├── api/                     # REST routes & dependency injection
│   │   ├── engine/                  # OR-Tools CP-SAT discrete-time solver
│   │   └── services/                # ConflictValidator, AuditLogger, etc.
│   ├── tests/                       # Unit, Solver, API & E2E acceptance tests
│   └── pyproject.toml               # Pinned backend dependencies
├── frontend/
│   ├── src/
│   │   ├── api/client.ts            # Type-safe API client
│   │   ├── components/              # AppLayout, Header, Sidebar, StatusBadge
│   │   ├── features/                # Dashboard, Schedule, Disruptions, Optimisation, Review, Reports
│   │   ├── types/api.ts             # Domain TypeScript definitions
│   │   └── index.css                # Tailwind tokens & dark aesthetics
│   ├── package.json                 # Pinned frontend dependencies
│   └── vite.config.ts               # Vite build config
├── infra/
│   ├── Dockerfile.backend           # Python 3.11 container
│   ├── Dockerfile.frontend          # Nginx React SPA container
│   └── docker-compose.yml           # PostgreSQL + App orchestration
├── ARCHITECTURE.md                  # Comprehensive architectural specification
├── IMPLEMENTATION_PLAN.md           # Implementation roadmap & verification matrix
├── .env.example                     # Environment configuration template
└── README.md                        # Documentation & walkthrough guide
```
