import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import SessionLocal
from app.db.migrate import upgrade_to_head
from app.db.seed import seed_database
from app.models.weather_models import Location
from app.services.weather_service import prefetch_weather

logger = logging.getLogger(__name__)


def _warm_weather_cache() -> None:
    try:
        with SessionLocal() as db:
            locations = db.query(Location).all()
            db.expunge_all()
        prefetch_weather(locations)
    except Exception as e:  # never let warm-up affect the app
        logger.warning("Weather warm-up failed: %s", e)
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: apply schema migrations, then seed demo data
    upgrade_to_head()
    with SessionLocal() as db:
        seed_database(db)
    if settings.WEATHER_PREFETCH_ON_STARTUP:
        threading.Thread(target=_warm_weather_cache, name="weather-warmup", daemon=True).start()
    yield
    # Shutdown logic if needed


app = FastAPI(
    title=settings.APP_NAME,
    description="Secure Decision-Support Scheduling & Dynamic Rescheduling System (PS 26250)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# CORS Middleware
origins = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.detail,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # In production, do not leak raw stack traces
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected internal server error occurred." if not settings.DEBUG else str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint validating service and database connectivity."""
    db_status = "UP"
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"DOWN: {str(e)}"

    return {
        "status": "HEALTHY" if "DOWN" not in db_status else "DEGRADED",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
