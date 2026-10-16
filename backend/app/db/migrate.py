"""Run Alembic migrations programmatically (used at app startup)."""
import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401  (registers all tables on Base.metadata)

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
BASELINE_REVISION = "0001"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False  # keep uvicorn's logging config
    return cfg


def upgrade_to_head() -> None:
    """
    Bring the database schema to the latest revision.
    A database with tables but no version table was built without Alembic: if it already
    matches the models (e.g. created with create_all) it is stamped at head, otherwise at
    the baseline so later migrations apply on top of it.
    """
    cfg = _alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and "users" in tables:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        target = "head" if not diff else BASELINE_REVISION
        logger.info("Existing schema without alembic_version; stamping %s", target)
        command.stamp(cfg, target)
    command.upgrade(cfg, "head")
