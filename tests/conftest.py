"""Shared fixtures: tests run against a dedicated `ecommerce_test` database.

Requires the Docker stack to be running (`docker compose up -d`). If PostgreSQL
is unreachable, database tests are skipped rather than failing.
"""

import os

# Must be set before any settings are loaded; load_dotenv() never overrides them.
# Each store gets its own test namespace so real data is never touched.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "ecommerce_test")
os.environ["REDIS_DB"] = os.environ.get("TEST_REDIS_DB", "15")
os.environ["MONGO_DB"] = os.environ.get("TEST_MONGO_DB", "ecommerce_sessions_test")

import psycopg2  # noqa: E402
import pytest  # noqa: E402
import redis  # noqa: E402
from psycopg2 import sql  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

from ecommerce_pipeline import db  # noqa: E402
from ecommerce_pipeline.cache import get_redis  # noqa: E402
from ecommerce_pipeline.config import load_settings  # noqa: E402
from ecommerce_pipeline.schema import create_tables, drop_tables  # noqa: E402
from ecommerce_pipeline.sessions import SessionStore  # noqa: E402


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


@pytest.fixture
def redis_client():
    """Client on the test Redis DB, flushed before and after each test."""
    client = get_redis()
    try:
        client.ping()
    except redis.ConnectionError as exc:
        pytest.skip(f"Redis not reachable ({exc}); run `docker compose up -d`")
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


@pytest.fixture
def session_store():
    """SessionStore on an empty test collection."""
    settings = load_settings()
    client: MongoClient = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        pytest.skip(f"MongoDB not reachable ({exc}); run `docker compose up -d`")
    collection = client[settings.mongo_db]["sessions"]
    collection.drop()
    store = SessionStore(collection)
    store.ensure_indexes()
    yield store
    collection.drop()
    client.close()


def fetch_one(query: str, params: tuple = ()):
    """Small helper for assertions that read straight from the database."""
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()
