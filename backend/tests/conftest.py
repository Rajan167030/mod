import os

# Must be set before any app module is imported: the engine is created at import time.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BCRYPT_ROUNDS"] = "4"  # minimum cost; hashing speed is irrelevant in tests
os.environ["WEATHER_PREFETCH_ON_STARTUP"] = "false"  # no background network calls in tests
os.environ["SEED_CONTESTED_DEMO"] = "false"  # existing tests assume the original scenario; contested has its own tests

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.db.seed import seed_database
from app.core.security import create_access_token
from app.models.all_models import User
from app.services import metar_service, weather_service

OPEN_METEO_PATTERN = r"https://api\.open-meteo\.com/.*"
AWC_PATTERN = r"https://aviationweather\.gov/api/data/metar.*"


def make_open_meteo_payload(hours: int = 48, wind_kmh: float = 12.0, temp_c: float = 8.0) -> dict:
    """Minimal Open-Meteo hourly payload starting at today 00:00 UTC (naive timestamps, as the API returns)."""
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]
    n = len(times)
    return {
        "hourly_units": {"temperature_2m": "°C", "precipitation": "mm", "wind_speed_10m": "km/h"},
        "hourly": {
            "time": times,
            "temperature_2m": [temp_c] * n,
            "precipitation": [0.0] * n,
            "wind_speed_10m": [wind_kmh] * n,
            "weather_code": [1] * n,
            "wind_gusts_10m": [wind_kmh + 10] * n,
            "wind_direction_10m": [270] * n,
            "visibility": [20000] * n,
            "cloud_cover": [30] * n,
            "relative_humidity_2m": [50] * n,
            "pressure_msl": [1015] * n,
            "dew_point_2m": [temp_c - 6] * n,
        },
    }


def open_meteo_response(request: httpx.Request) -> httpx.Response:
    """Mirror Open-Meteo: one point -> object, several comma-separated points -> list."""
    n = len(request.url.params["latitude"].split(","))
    body = make_open_meteo_payload() if n == 1 else [make_open_meteo_payload() for _ in range(n)]
    return httpx.Response(200, json=body)


SAMPLE_METAR = [
    {
        "icaoId": "VILH",
        "obsTime": 1792132200,
        "temp": 9,
        "dewp": -4,
        "wdir": 70,
        "wspd": 5,
        "visib": 3.73,
        "altim": 1028,
        "rawOb": "METAR VILH 160630Z 07005KT 6000 FEW050 SCT070 09/M04 Q1028 NOSIG",
        "rawTaf": "TAF VILH 160330Z 1606/1618 25010KT 6000 SCT060",
        "lat": 34.136,
        "lon": 77.546,
        "elev": 3256,
        "name": "Leh Kushok Bakula Arpt, JK, IN",
        "fltCat": "MVFR",
        "clouds": [{"cover": "FEW", "base": 5000}, {"cover": "SCT", "base": 7000}],
    }
]


@pytest.fixture(autouse=True)
def mock_weather_providers():
    """No test talks to the real internet. Individual tests can override the routes."""
    weather_service._weather_cache.clear()
    weather_service._failed_until.clear()
    metar_service._metar_cache.clear()
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=OPEN_METEO_PATTERN).mock(side_effect=open_meteo_response)
        router.get(url__regex=AWC_PATTERN).mock(return_value=httpx.Response(200, json=SAMPLE_METAR))
        yield router
    weather_service._weather_cache.clear()
    metar_service._metar_cache.clear()


@pytest.fixture(scope="function")
def db_session():
    """Fresh schema + seed data for each test."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed_database(db)
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    with TestClient(app) as test_client:
        yield test_client


def _headers(db_session, email: str) -> dict:
    user = db_session.query(User).filter_by(email=email).first()
    token = create_access_token(subject=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(db_session):
    return _headers(db_session, "admin@airops.demo")


@pytest.fixture
def planner_headers(db_session):
    return _headers(db_session, "planner@airops.demo")


@pytest.fixture
def reviewer_headers(db_session):
    return _headers(db_session, "reviewer@airops.demo")


@pytest.fixture
def viewer_headers(db_session):
    return _headers(db_session, "viewer@airops.demo")
