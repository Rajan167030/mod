"""
Unit tests for Weather Rules Engine.
Tests threshold comparisons, alert generation, and severity classification.
"""
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.weather_rules_service import evaluate_weather_rules, get_default_thresholds
from app.schemas.weather_schemas import WeatherThresholdConfig

LOCATION = SimpleNamespace(id="loc-1", name="Base Alpha")


def _point(**overrides):
    point = {
        "forecast_timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature_celsius": 15.0,
        "precipitation_mm": 1.0,
        "wind_speed_kmh": 20.0,
        "weather_condition": "Clear sky",
    }
    point.update(overrides)
    return point


def _evaluate(points, thresholds=None):
    return evaluate_weather_rules(points, LOCATION, "FRESH", time.time(), thresholds)


def test_weather_rules_normal_conditions():
    alerts = _evaluate([_point()], get_default_thresholds())
    assert [a for a in alerts if a.severity in ("CRITICAL", "WARNING")] == []


def test_weather_rules_wind_warning_and_critical():
    warn = [a for a in _evaluate([_point(wind_speed_kmh=50.0)]) if a.variable == "wind_speed"]
    assert len(warn) == 1
    assert warn[0].severity == "WARNING"

    crit = [a for a in _evaluate([_point(wind_speed_kmh=75.0)]) if a.variable == "wind_speed"]
    assert len(crit) == 1
    assert crit[0].severity == "CRITICAL"


def test_weather_rules_custom_thresholds():
    custom = WeatherThresholdConfig(
        wind_speed_warning_kmh=30.0,
        wind_speed_critical_kmh=50.0,
        precipitation_warning_mm=2.0,
        precipitation_critical_mm=8.0,
    )
    alerts = _evaluate([_point(precipitation_mm=3.5, wind_speed_kmh=35.0, temperature_celsius=5.0)], custom)
    variables = {a.variable for a in alerts}
    assert "wind_speed" in variables
    assert "precipitation" in variables


def test_weather_rules_low_temperature():
    alerts = _evaluate([_point(temperature_celsius=-30.0)])
    temp = [a for a in alerts if a.variable == "temperature"]
    assert len(temp) == 1
    assert temp[0].severity == "CRITICAL"


def test_missing_data_is_never_treated_as_safe():
    alerts = evaluate_weather_rules([], LOCATION, "UNKNOWN", None)
    assert len(alerts) == 1
    assert alerts[0].variable == "all"
    assert alerts[0].severity == "WARNING"
