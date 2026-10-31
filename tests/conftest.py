"""Shared fixtures: tests run against a dedicated `ecommerce_test` database.

Requires the Docker stack to be running (`docker compose up -d`). If PostgreSQL
is unreachable, database tests are skipped rather than failing.
"""

import os

# Must be set before any settings are loaded; load_dotenv() never overrides it.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "ecommerce_test")

import psycopg2  # noqa: E402
import pytest  # noqa: E402
from psycopg2 import sql  # noqa: E402

from ecommerce_pipeline import db  # noqa: E402
from ecommerce_pipeline.config import load_settings  # noqa: E402
from ecommerce_pipeline.schema import create_tables, drop_tables  # noqa: E402


def _ensure_test_database(settings) -> None:
    """Create the test database if it doesn't exist (connects via the `postgres` db)."""
    admin_dsn = settings.postgres_dsn.replace(f"dbname={settings.postgres_db}", "dbname=postgres")
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True  # CREATE DATABASE cannot run inside a transaction
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,))
            if cur.fetchone() is None:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.postgres_db))
                )
    finally:
        conn.close()


@pytest.fixture(scope="session")
def pg_settings():
    settings = load_settings()
    try:
        _ensure_test_database(settings)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable ({exc}); run `docker compose up -d`")
    return settings


@pytest.fixture(scope="session")
def schema(pg_settings):
    """Recreate the schema once per test session and open the connection pool."""
    conn = psycopg2.connect(pg_settings.postgres_dsn)
    try:
        drop_tables(conn)
        create_tables(conn)
    finally:
        conn.close()
    db.init_pool(pg_settings, minconn=1, maxconn=5)
    yield
    db.close_pool()


@pytest.fixture
def clean_db(schema):
    """Empty every table (and reset identity counters) before each test."""
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE order_items, orders, products, categories, customers "
            "RESTART IDENTITY CASCADE"
        )
    yield


def fetch_one(query: str, params: tuple = ()):
    """Small helper for assertions that read straight from the database."""
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()
