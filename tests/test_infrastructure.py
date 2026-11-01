"""Settings, connection pool / transaction semantics, and small helpers."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from ecommerce_pipeline import db
from ecommerce_pipeline.cache import _to_json
from ecommerce_pipeline.config import load_settings
from ecommerce_pipeline.sessions import SessionStore
from tests.conftest import fetch_one


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("REDIS_DB", "3")

    settings = load_settings()

    assert settings.postgres_port == 6543
    assert settings.redis_db == 3
    assert "port=6543" in settings.postgres_dsn


def test_mongo_uri_escapes_special_characters(monkeypatch):
    monkeypatch.setenv("MONGO_USER", "app@team")
    monkeypatch.setenv("MONGO_PASSWORD", "p:ss/w@rd")

    uri = load_settings().mongo_uri

    assert uri.startswith("mongodb://app%40team:p%3Ass%2Fw%40rd@")
    assert uri.endswith("/?authSource=admin")


@pytest.mark.usefixtures("clean_db")
def test_transaction_rolls_back_on_exception():
    with pytest.raises(RuntimeError):
        with db.transaction() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO categories (name) VALUES ('Ghost')")
            raise RuntimeError("boom")

    assert fetch_one("SELECT count(*) FROM categories")[0] == 0


@pytest.mark.usefixtures("clean_db")
def test_pool_connections_are_returned_and_reused():
    for _ in range(20):  # more borrows than the pool's maxconn (5)
        with db.get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            conn.rollback()


def test_to_json_handles_money_and_dates():
    assert _to_json(Decimal("19.90")) == "19.90"
    assert _to_json(date(2026, 1, 2)) == "2026-01-02"
    assert _to_json(datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    with pytest.raises(TypeError):
        _to_json(object())


def test_session_touch_updates_last_active(session_store):
    session_id = session_store.create_session()
    before = session_store.get_session(session_id)["last_active"]

    assert session_store.touch(session_id)
    assert session_store.get_session(session_id)["last_active"] >= before
    assert session_store.touch("missing") is False


def test_session_store_from_settings_creates_indexes(session_store):
    store = SessionStore.from_settings()

    assert "ttl_last_active" in store.collection.index_information()
