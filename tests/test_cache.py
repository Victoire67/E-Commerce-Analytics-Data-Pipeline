"""Redis cache-aside behaviour for the top-selling products list."""

from decimal import Decimal

import pytest

from ecommerce_pipeline import cache, crud

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture
def sales():
    """Three products with known sales: B (5 units) > A (3) > C (1)."""
    customer = crud.create_customer("Test", "Buyer", "buyer@example.com")
    a = crud.add_product("A", "Alpha", "Misc", Decimal("10.00"), 100)
    b = crud.add_product("B", "Bravo", "Misc", Decimal("2.50"), 100)
    c = crud.add_product("C", "Charlie", "Misc", Decimal("99.99"), 100)
    crud.create_order(customer, [(a, 3), (b, 5), (c, 1)])
    return {"customer": customer, "a": a, "b": b, "c": c}


def test_first_read_is_a_miss_then_a_hit(redis_client, sales):
    first = cache.get_top_products(redis_client)
    second = cache.get_top_products(redis_client)

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.products == second.products


def test_cached_list_is_ranked_by_units_sold(redis_client, sales):
    products = cache.get_top_products(redis_client).products

    assert [p["product_id"] for p in products] == [sales["b"], sales["a"], sales["c"]]
    assert [p["rank"] for p in products] == [1, 2, 3]
    assert products[0]["revenue"] == "12.50"  # Decimal kept exact as a string


def test_cache_entry_has_ttl(redis_client, sales):
    cache.get_top_products(redis_client, ttl=120)

    assert 0 < cache.cache_ttl(redis_client) <= 120


def test_limit_is_respected_and_cached_separately(redis_client, sales):
    top1 = cache.get_top_products(redis_client, limit=1)
    top10 = cache.get_top_products(redis_client, limit=10)

    assert len(top1.products) == 1
    assert len(top10.products) == 3
    assert top10.from_cache is False  # different key


def test_stale_until_invalidated(redis_client, sales):
    cache.get_top_products(redis_client)
    crud.create_order(sales["customer"], [(sales["c"], 10)])  # C becomes the best seller

    stale = cache.get_top_products(redis_client)
    assert stale.products[0]["product_id"] == sales["b"]  # cache still serves old ranking

    assert cache.invalidate_top_products(redis_client) == 1
    fresh = cache.get_top_products(redis_client)
    assert fresh.from_cache is False
    assert fresh.products[0]["product_id"] == sales["c"]


def test_cancelled_orders_do_not_count(redis_client, sales):
    order_id = crud.create_order(sales["customer"], [(sales["c"], 50)])
    crud.update_order_status(order_id, "cancelled")

    products = cache.get_top_products(redis_client).products
    assert products[0]["product_id"] == sales["b"]
