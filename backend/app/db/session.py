from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from app.core.config import settings

# Engine configuration
engine_kwargs = {"pool_pre_ping": True, "echo": False}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if settings.DATABASE_URL in ("sqlite://", "sqlite:///:memory:"):
        # In-memory SQLite is per-connection; share one connection so every session sees the same DB.
        engine_kwargs["poolclass"] = StaticPool

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

if engine.dialect.name == "sqlite" and "poolclass" not in engine_kwargs:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        # WAL lets reads continue while a write is in progress; busy_timeout waits instead of failing fast
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Provide a transactional database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
