from pathlib import Path
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Secure AirOps Scheduler"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = "super-secret-scheduling-key-for-development-only-min-32-chars-long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    # When True, requests without a token act as the demo ADMIN. Bypasses RBAC; local dev only.
    AUTH_DEV_BYPASS: bool = False
    # bcrypt work factor. 12 is a sensible production default; tests lower it for speed.
    BCRYPT_ROUNDS: int = 12
    # Seed the "Exercise WINTER LIFT" contested demo scenario if it is missing
    SEED_CONTESTED_DEMO: bool = True

    # Planning copilot. COPILOT_PROVIDER picks the model provider: "groq" or "anthropic".
    COPILOT_PROVIDER: str = "groq"
    # Anthropic (Claude): credentials come from ANTHROPIC_API_KEY
    COPILOT_MODEL: str = "claude-opus-5-5"
    COPILOT_EFFORT: str = "medium"
    # Groq
    GROQ_API_KEY: str = ""
    COPILOT_GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Database
    DATABASE_URL: str = "sqlite:///./scheduler.db"

    # Reference data pack (real Indian airfields, airspace, aircraft types); see data/india/README.md
    REFERENCE_DATA_DIR: str = str(Path(__file__).resolve().parents[3] / "data" / "india" / "real")

    # CORS
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Optimisation Engine Defaults
    SOLVER_MAX_TIME_SECONDS: int = 30
    SOLVER_NUM_WORKERS: int = 4
    SOLVER_RANDOM_SEED: int = 42

    # Weather Provider Settings
    WEATHER_PROVIDER_BASE_URL: str = "https://api.open-meteo.com/v1"
    WEATHER_CACHE_TTL_SECONDS: int = 900
    WEATHER_REQUEST_TIMEOUT_SECONDS: int = 10
    WEATHER_STALE_MULTIPLIER: int = 2
    # Fetch every site's forecast in the background at startup so the first page load is fast
    WEATHER_PREFETCH_ON_STARTUP: bool = True

    # Weather Demonstration Thresholds (illustrative, not operational)
    WEATHER_WIND_WARNING_KMH: float = 45.0
    WEATHER_WIND_CRITICAL_KMH: float = 65.0
    WEATHER_PRECIP_WARNING_MM: float = 5.0
    WEATHER_PRECIP_CRITICAL_MM: float = 15.0
    WEATHER_TEMP_LOW_WARNING_C: float = -10.0
    WEATHER_TEMP_LOW_CRITICAL_C: float = -25.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
