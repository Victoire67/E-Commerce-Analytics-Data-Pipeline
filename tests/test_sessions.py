"""MongoDB sessions/carts, and checkout across MongoDB, PostgreSQL and Redis."""

from decimal import Decimal

import pytest

from ecommerce_pipeline import cache, crud
from ecommerce_pipeline.checkout import AnonymousSessionError, EmptyCartError, checkout
from tests.conftest import fetch_one


def test_create_and_get_session(session_store):
    session_id = session_store.create_session(customer_id=7, device={"os": "android"})

    session = session_store.get_session(session_id)

    assert session["customer_id"] == 7
    assert session["device"] == {"os": "android"}
    assert session["cart"] == []


def test_add_to_cart_merges_same_product(session_store):
    session_id = session_store.create_session()

    session_store.add_to_cart(session_id, product_id=1, quantity=2)
    session_store.add_to_cart(session_id, product_id=2)
    cart = session_store.add_to_cart(session_id, product_id=1, quantity=3)

    assert [(line["product_id"], line["quantity"]) for line in cart] == [(1, 5), (2, 1)]


def test_set_quantity_and_remove(session_store):
    session_id = session_store.create_session()
    session_store.add_to_cart(session_id, 1, 2)
    session_store.add_to_cart(session_id, 2, 1)

    assert session_store.set_quantity(session_id, 1, 9)[0]["quantity"] == 9
    assert [line["product_id"] for line in session_store.set_quantity(session_id, 1, 0)] == [2]
    assert session_store.remove_from_cart(session_id, 2) == []


def test_invalid_quantity_and_missing_session(session_store):
    session_id = session_store.create_session()

    with pytest.raises(ValueError):
        session_store.add_to_cart(session_id, 1, 0)
    with pytest.raises(KeyError):
        session_store.add_to_cart("no-such-session", 1, 1)


def test_attach_customer_keeps_cart(session_store):
    session_id = session_store.create_session()
    session_store.add_to_cart(session_id, 5, 1)

    assert session_store.attach_customer(session_id, 42)
    assert session_store.get_session(session_id)["customer_id"] == 42
    assert len(session_store.get_cart(session_id)) == 1
    assert [s["_id"] for s in session_store.sessions_for_customer(42)] == [session_id]


def test_ttl_index_exists(session_store):
    indexes = session_store.collection.index_information()

    assert indexes["ttl_last_active"]["expireAfterSeconds"] == session_store.ttl_seconds


def test_end_session(session_store):
    session_id = session_store.create_session()

    assert session_store.end_session(session_id)
    assert session_store.get_session(session_id) is None


def test_most_carted_products_aggregation(session_store):
    for product_ids in ([1, 2], [1], [1, 3]):
        session_id = session_store.create_session()
        for product_id in product_ids:
            session_store.add_to_cart(session_id, product_id, 2)

    top = session_store.most_carted_products(limit=2)

    assert top[0] == {"_id": 1, "carts": 3, "units": 6}
    assert len(top) == 2


# --- checkout: MongoDB -> PostgreSQL -> Redis ----------------------------------


@pytest.fixture
def shop(clean_db):
    customer = crud.create_customer("Cart", "Owner", "cart@example.com")
    mug = crud.add_product("MUG", "Mug", "Kitchen", Decimal("5.00"), stock_quantity=2)
    return customer, mug


def test_checkout_creates_order_clears_cart_and_invalidates_cache(
    session_store, redis_client, shop
):
    customer, mug = shop
    cache.get_top_products(redis_client)  # warm the cache
    session_id = session_store.create_session(customer_id=customer)
    session_store.add_to_cart(session_id, mug, 2)

    order_id = checkout(session_store, redis_client, session_id)

    assert crud.get_customer_orders(customer)[0]["order_id"] == order_id
    assert session_store.get_cart(session_id) == []
    assert cache.get_top_products(redis_client).from_cache is False


def test_failed_checkout_keeps_cart_and_stock(session_store, redis_client, shop):
    customer, mug = shop
    session_id = session_store.create_session(customer_id=customer)
    session_store.add_to_cart(session_id, mug, 3)  # only 2 in stock

    with pytest.raises(crud.InsufficientStockError):
        checkout(session_store, redis_client, session_id)

    assert session_store.get_cart(session_id)[0]["quantity"] == 3
    assert fetch_one("SELECT stock_quantity FROM products WHERE product_id = %s", (mug,))[0] == 2


def test_checkout_rejects_anonymous_and_empty_carts(session_store, redis_client, shop):
    customer, mug = shop
    anonymous = session_store.create_session()
    session_store.add_to_cart(anonymous, mug, 1)

    with pytest.raises(AnonymousSessionError):
        checkout(session_store, redis_client, anonymous)
    with pytest.raises(EmptyCartError):
        checkout(session_store, redis_client, session_store.create_session(customer_id=customer))
