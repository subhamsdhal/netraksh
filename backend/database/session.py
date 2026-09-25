"""
NETRAKSH Backend — Database connection and session management.
"""
import logging
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.models.orm import Base

logger = logging.getLogger(__name__)

# SQLite requires connect_args={'check_same_thread': False} and does not support pool_size/max_overflow
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=settings.DEBUG,
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=settings.DEBUG,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def check_alembic_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current_rev = context.get_current_revision()

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    head_rev = script.get_current_head()

    if current_rev is None:
        raise RuntimeError("Missing alembic_version. Run alembic upgrade head")
    if current_rev != head_rev:
        raise RuntimeError(f"Database schema out of date. Current: {current_rev}, Head: {head_rev}")

def init_db() -> None:
    """Create all tables if they don't exist. Used for dev/test without migrations."""
    if settings.ENV == "production":
        check_alembic_revision()
        logger.info("Database schema verified via Alembic")
    else:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified via create_all")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session, closes after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
