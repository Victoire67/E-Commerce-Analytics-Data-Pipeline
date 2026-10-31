"""Sample-data generator: volumes, integrity and reproducibility."""

import pytest

from ecommerce_pipeline.seed import seed_all
from tests.conftest import fetch_one

pytestmark = pytest.mark.usefixtures("clean_db")


def test_seed_inserts_requested_volumes():
    result = seed_all(customers=50, products=20, orders=200, seed=1)

    assert fetch_one("SELECT count(*) FROM customers")[0] == 50
    assert fetch_one("SELECT count(*) FROM products")[0] == 20
    assert fetch_one("SELECT count(*) FROM orders")[0] == 200
    assert fetch_one("SELECT count(*) FROM order_items")[0] == result.order_items
    assert 200 <= result.order_items <= 800  # 1-4 lines per order


def test_every_order_has_at_least_one_line():
    seed_all(customers=20, products=10, orders=100, seed=2)

    empty_orders = fetch_one(
        "SELECT count(*) FROM orders o "
        "WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.order_id)"
    )[0]
    assert empty_orders == 0


def test_metadata_varies_by_category():
    seed_all(customers=10, products=60, orders=10, seed=3)

    clothing_with_sizes = fetch_one(
        "SELECT count(*) FROM products p JOIN categories c USING (category_id) "
        "WHERE c.name = 'Clothing' AND p.metadata ? 'sizes'"
    )[0]
    clothing_total = fetch_one(
        "SELECT count(*) FROM products p JOIN categories c USING (category_id) "
        "WHERE c.name = 'Clothing'"
    )[0]
    assert clothing_total > 0
    assert clothing_with_sizes == clothing_total


def test_same_seed_produces_same_data():
    seed_all(customers=10, products=15, orders=20, seed=7)
    first = fetch_one("SELECT string_agg(name || price, ',' ORDER BY product_id) FROM products")

    seed_all(customers=10, products=15, orders=20, seed=7)
    second = fetch_one("SELECT string_agg(name || price, ',' ORDER BY product_id) FROM products")

    assert first == second
