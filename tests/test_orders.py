"""Transactional order processing: success path, rollback paths, and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from ecommerce_pipeline import crud
from tests.conftest import fetch_one

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture
def customer_id():
    return crud.create_customer("Grace", "Hopper", "grace@example.com")


@pytest.fixture
def products():
    shirt = crud.add_product("TS-1", "T-Shirt", "Clothing", Decimal("20.00"), stock_quantity=10)
    mug = crud.add_product("MUG-1", "Mug", "Kitchen", Decimal("5.50"), stock_quantity=3)
    return shirt, mug


def stock_of(product_id: int) -> int:
    return fetch_one("SELECT stock_quantity FROM products WHERE product_id = %s", (product_id,))[0]


def order_count() -> int:
    return fetch_one("SELECT count(*) FROM orders")[0]


def test_create_order_inserts_lines_and_decrements_stock(customer_id, products):
    shirt, mug = products

    order_id = crud.create_order(customer_id, [(shirt, 2), (mug, 1)])

    orders = crud.get_customer_orders(customer_id)
    assert [o["order_id"] for o in orders] == [order_id]
    assert orders[0]["total"] == Decimal("45.50")  # 2 * 20.00 + 1 * 5.50
    assert stock_of(shirt) == 8
    assert stock_of(mug) == 2


def test_order_keeps_price_at_time_of_purchase(customer_id, products):
    shirt, _ = products
    crud.create_order(customer_id, [(shirt, 1)])

    crud.update_product(shirt, price=Decimal("99.00"))

    item = crud.get_customer_orders(customer_id)[0]["items"][0]
    assert item["unit_price"] == Decimal("20.00")


def test_duplicate_product_lines_are_merged(customer_id, products):
    shirt, _ = products

    crud.create_order(customer_id, [(shirt, 1), (shirt, 2)])

    assert crud.get_customer_orders(customer_id)[0]["items"][0]["quantity"] == 3
    assert stock_of(shirt) == 7


def test_insufficient_stock_rolls_back_everything(customer_id, products):
    shirt, mug = products

    with pytest.raises(crud.InsufficientStockError):
        # Shirt is fine, mug is over-ordered: the whole order must fail.
        crud.create_order(customer_id, [(shirt, 2), (mug, 4)])

    assert order_count() == 0
    assert stock_of(shirt) == 10
    assert stock_of(mug) == 3


def test_unknown_product_rolls_back(customer_id, products):
    shirt, _ = products

    with pytest.raises(crud.ProductNotFoundError):
        crud.create_order(customer_id, [(shirt, 1), (9999, 1)])

    assert order_count() == 0
    assert stock_of(shirt) == 10


def test_unknown_customer_is_rejected(products):
    shirt, _ = products

    with pytest.raises(crud.CustomerNotFoundError):
        crud.create_order(424242, [(shirt, 1)])

    assert stock_of(shirt) == 10


@pytest.mark.parametrize("items", [[], [(1, 0)], [(1, -2)]])
def test_invalid_items_are_rejected_before_touching_the_database(customer_id, items):
    with pytest.raises(ValueError):
        crud.create_order(customer_id, items)


def test_get_customer_orders_newest_first(customer_id, products):
    shirt, mug = products
    first = crud.create_order(customer_id, [(shirt, 1)])
    second = crud.create_order(customer_id, [(mug, 1)])

    assert [o["order_id"] for o in crud.get_customer_orders(customer_id)] == [second, first]


def test_concurrent_orders_cannot_oversell(customer_id, products):
    """Five parallel buyers race for 3 mugs: SELECT ... FOR UPDATE allows exactly 3."""
    _, mug = products

    def buy_one():
        try:
            crud.create_order(customer_id, [(mug, 1)])
            return True
        except crud.InsufficientStockError:
            return False

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: buy_one(), range(5)))

    assert results.count(True) == 3
    assert stock_of(mug) == 0
