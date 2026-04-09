"""Database configuration and session management."""

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool, NullPool
import os
import time

# Use SQLite for simplicity - can be swapped for PostgreSQL later
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./debate.db")

# Connection pool settings
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
POOL_MAX_OVERFLOW = int(os.getenv("DB_POOL_MAX_OVERFLOW", "10"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "900"))  # 15 minutes
POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"

# Determine pool class based on database type
if DATABASE_URL.startswith("sqlite"):
    pool_class = NullPool  # SQLite doesn't handle pooling well
else:
    pool_class = QueuePool

common_kwargs = {
    "echo": False,
    "pool_recycle": POOL_RECYCLE,
    "pool_pre_ping": POOL_PRE_PING,
}

if pool_class == NullPool:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        **common_kwargs,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        poolclass=pool_class,
        pool_size=POOL_SIZE,
        max_overflow=POOL_MAX_OVERFLOW,
        **common_kwargs,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable foreign key support for SQLite."""
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db():
    """Generator dependency — FastAPI handles cleanup automatically."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get a new database session."""
    return SessionLocal()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


def check_db_health() -> dict:
    """Check database connectivity and return health status."""
    start = time.time()
    try:
        with engine.connect() as conn:
            if DATABASE_URL.startswith("sqlite"):
                conn.execute(text("SELECT 1"))
            else:
                conn.execute(text("SELECT 1"))
            latency_ms = (time.time() - start) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "pool_size": POOL_SIZE,
                "pool_max_overflow": POOL_MAX_OVERFLOW,
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "latency_ms": round((time.time() - start) * 1000, 2),
        }
