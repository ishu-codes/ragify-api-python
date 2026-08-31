"""Shared fixtures for the ragify-api test suite.

Rate limiting and credits are PostgreSQL-backed, so the tests run against a
real Postgres database. Point ``TEST_DATABASE_URL`` at an empty database (for
example the one started by ``make infra-up`` or a dedicated test container);
the schema is created automatically on first use.
"""

import os
import sys
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Make the api-python package importable regardless of the pytest invocation cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ragify:ragify@localhost:5432/ragify_test",
)

# The application reads DATABASE_URL at import time; point it at the test
# database before any application module is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault(
    "JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef"
)
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

# Pin quota/rate-limit defaults so tests are deterministic regardless of the
# caller's environment (ambient RATE_LIMIT_*/FREE_MONTHLY_CREDITS variables
# must not leak into the application's import-time config).
_QUOTA_ENV = {
    "RATE_LIMIT_REGISTER": "5",
    "RATE_LIMIT_REGISTER_DAY": "20",
    "RATE_LIMIT_LOGIN": "10",
    "RATE_LIMIT_LOGIN_DAY": "50",
    "RATE_LIMIT_API_MIN": "120",
    "RATE_LIMIT_QUERY_MIN": "10",
    "RATE_LIMIT_QUERY_DAY": "200",
    "RATE_LIMIT_UPLOAD_HOUR": "10",
    "RATE_LIMIT_UPLOAD_DAY": "20",
    "RATE_LIMIT_WORKSPACE_CREATE_HOUR": "10",
    "RATE_LIMIT_WORKSPACE_CREATE_DAY": "50",
    "FREE_MONTHLY_CREDITS": "50",
    "QUERY_CREDIT_COST": "1",
    "UPLOAD_CREDIT_STRIDE_BYTES": str(5 * 1024 * 1024),
    "MAX_WORKSPACES": "3",
    "MAX_STORAGE_BYTES": str(50 * 1024 * 1024),
}
for _name, _value in _QUOTA_ENV.items():
    os.environ[_name] = _value


async def _ensure_database() -> None:
    """Create the test database if it does not exist yet."""
    url = make_url(TEST_DATABASE_URL)
    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", url.database
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


async def _create_schema() -> None:
    from src.auth import models as auth_models  # noqa: F401
    from src.config.models import Base
    from src.quotas import models as quota_models  # noqa: F401
    from src.workspace import models as workspace_models  # noqa: F401

    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _truncate_all() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE rate_limits, credit_ledger, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
async def _database() -> None:
    await _ensure_database()
    await _create_schema()


@pytest.fixture(autouse=True)
async def _clean_tables() -> None:
    yield
    await _truncate_all()


@pytest.fixture()
def app():
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
async def db():
    engine = create_async_engine(TEST_DATABASE_URL)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()
