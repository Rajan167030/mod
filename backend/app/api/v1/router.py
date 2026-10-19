from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, scenarios, resources, tasks, schedules,
    disruptions, optimisation, approvals, reports, audit,
    locations, weather, coa, replay, copilot, ontology, imports, alerts, branches, ops_layers, reference, command
)

api_router = APIRouter()

# Authentication & Current User
api_router.include_router(auth.router)

# Core Operational Entities
api_router.include_router(scenarios.router)
api_router.include_router(resources.router)
api_router.include_router(tasks.router)

# Schedules & Validation
api_router.include_router(schedules.router)

# Synthetic Disruptions
api_router.include_router(disruptions.router)

# Optimisation & Solver
api_router.include_router(optimisation.router)

# Courses of Action (alternative plans)
api_router.include_router(coa.router)

# Live exercise replay
api_router.include_router(replay.router)

# Planning copilot (Claude)
api_router.include_router(copilot.router)

# Object explorer & link graph
api_router.include_router(ontology.router)

# Data import (CSV / Excel)
api_router.include_router(imports.router)

# Alert rules and scenario branches
api_router.include_router(alerts.router)
api_router.include_router(branches.router)

# Threats and airspace, crews, stores, predicted risk
api_router.include_router(ops_layers.router)

# Reference data for the theatre map
api_router.include_router(reference.router)

# Mission assignment, force capacity, execution on the day
api_router.include_router(command.router)

# Review & Approvals
api_router.include_router(approvals.router)

# Reports & KPIs
api_router.include_router(reports.router)

# Security Audit Ledger
api_router.include_router(audit.router)

# Locations & Geospatial
api_router.include_router(locations.router)

# Weather Data & Alerts
api_router.include_router(weather.router)

