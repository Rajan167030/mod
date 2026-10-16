from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, scenarios, resources, tasks, schedules,
    disruptions, optimisation, approvals, reports, audit,
    locations, weather, coa, replay, copilot
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

