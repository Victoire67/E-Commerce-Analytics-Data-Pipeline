"""CRUD behaviour for customers and products, plus SQL-injection safety."""

from decimal import Decimal

import psycopg2
import pytest

from ecommerce_pipeline import crud
from tests.conftest import fetch_one

pytestmark = pytest.mark.usefixtures("clean_db")


def test_create_and_get_customer():
    customer_id = crud.create_customer("Ada", "Lovelace", "ada@example.com", country="UK")

    customer = crud.get_customer(customer_id)

    assert customer["email"] == "ada@example.com"
    assert customer["country"] == "UK"


def test_duplicate_email_is_rejected():
    crud.create_customer("Ada", "Lovelace", "ada@example.com")

    with pytest.raises(psycopg2.errors.UniqueViolation):
        crud.create_customer("Other", "Person", "ada@example.com")


def test_add_product_creates_category_and_stores_jsonb_metadata():
    metadata = {"colors": ["red", "blue"], "sizes": ["M", "L"]}

    product_id = crud.add_product("TS-001", "T-Shirt", "Clothing", Decimal("19.99"), 10, metadata)
    product = crud.get_product(product_id)

    assert product["category"] == "Clothing"
    assert product["price"] == Decimal("19.99")
    assert product["metadata"] == metadata  # JSONB comes back as a dict


def test_get_or_create_category_is_idempotent():
    first = crud.get_or_create_category("Books")
    second = crud.get_or_create_category("Books")

    assert first == second
    assert fetch_one("SELECT count(*) FROM categories")[0] == 1


def test_negative_price_violates_check_constraint():
    with pytest.raises(psycopg2.errors.CheckViolation):
        crud.add_product("BAD-1", "Broken", "Misc", Decimal("-1.00"))


def test_update_product_changes_only_given_fields():
    product_id = crud.add_product("MUG-1", "Mug", "Kitchen", Decimal("8.50"), 5, {"color": "white"})

    assert crud.update_product(product_id, price=Decimal("9.00"))
    product = crud.get_product(product_id)

    assert product["price"] == Decimal("9.00")
    assert product["stock_quantity"] == 5  # untouched
    assert product["metadata"] == {"color": "white"}  # untouched


def test_update_missing_product_returns_false():
    assert crud.update_product(999, price=Decimal("1.00")) is False


def test_delete_product():
    product_id = crud.add_product("DEL-1", "Temp", "Misc", Decimal("1.00"))

    assert crud.delete_product(product_id) is True
    assert crud.get_product(product_id) is None


def test_sql_injection_payload_is_stored_as_plain_text():
    payload = "x'); DROP TABLE customers; --"

    customer_id = crud.create_customer(payload, "Tables", "bobby@example.com")

    # The table still exists and the payload was stored verbatim, not executed.
    assert crud.get_customer(customer_id)["first_name"] == payload
    assert fetch_one("SELECT count(*) FROM customers")[0] == 1
