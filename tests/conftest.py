"""
Shared fixtures for integration tests against the live PostGIS database.

Requires the Docker-Compose stack to be running (db on port 5433).
Tests are read-only — no data is modified.
"""
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient


# ── Database connection ───────────────────────────────────────────────────────

_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/dwt",
)


@pytest.fixture(scope="session")
def db_engine():
    """Session-scoped SQLAlchemy engine connected to the live database."""
    engine = create_engine(_DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine) -> Session:
    """Function-scoped read-only session. Rolls back any accidental writes."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


# ── FastAPI test client (wired to real DB) ────────────────────────────────────

@pytest.fixture(scope="session")
def api_client(db_engine):
    """
    TestClient wired to the real database via dependency override.
    All API calls go through the actual SQL queries against real data.
    """
    # Override DATABASE_URL before importing the app so the module-level
    # engine picks up the test URL on first import.
    os.environ["DATABASE_URL"] = _DB_URL

    from api.main import app
    from api.db import get_db

    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
