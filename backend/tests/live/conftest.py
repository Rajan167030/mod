"""
Live system tests: start the real backend with uvicorn and talk to it over HTTP.

Nothing is mocked here. Weather comes from Open-Meteo and NOAA AWC, the copilot
calls Groq with the key in backend/.env, and the database is a real SQLite file.
The file is a throwaway copy, so scheduler.db is never touched.

Run with:  python -m pytest -m live
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def mock_weather_providers():
    """Overrides the suite-wide internet mock: live tests use the real providers."""
    yield None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    port = _free_port()
    db_dir = tempfile.mkdtemp(prefix="airops-live-")
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{Path(db_dir, 'live.db').as_posix()}",
        "SEED_CONTESTED_DEMO": "true",
        "WEATHER_PREFETCH_ON_STARTUP": "false",  # the tests trigger the first real fetch themselves
        "PYTHONIOENCODING": "utf-8",
    }
    log = open(Path(db_dir, "server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 90
        while True:
            if proc.poll() is not None:
                pytest.fail(f"Backend exited during startup; see {log.name}")
            try:
                if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.time() > deadline:
                pytest.fail(f"Backend did not start within 90 s; see {log.name}")
            time.sleep(0.5)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture(scope="session")
def http(live_server):
    with httpx.Client(base_url=f"{live_server}/api/v1", timeout=120) as c:
        yield c


def _login(http: httpx.Client, email: str, password: str) -> dict:
    res = http.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture(scope="session")
def planner(http):
    return _login(http, "planner@airops.demo", "PlannerPass123!")


@pytest.fixture(scope="session")
def viewer(http):
    return _login(http, "viewer@airops.demo", "ViewerPass123!")
