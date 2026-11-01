"""Window-function and CTE analytics, checked against hand-computed results."""

from datetime import date
from decimal import Decimal

import pytest

from ecommerce_pipeline import analytics, crud
from tests.conftest import fetch_one

pytestmark = pytest.mark.usefixtures("clean_db")


def place_order(customer_id, items, *, on=None, status=None):
    order_id = crud.create_order(customer_id, items)
    with crud.transaction() as conn, conn.cursor() as cur:
        if on:
            cur.execute("UPDATE orders SET order_date = %s WHERE order_id = %s", (on, order_id))
        if status:
            cur.execute("UPDATE orders SET status = %s WHERE order_id = %s", (status, order_id))
    return order_id


@pytest.fixture
def store():
    """
    Products:  shirt 10.00, jeans 50.00 (Clothing); mouse 20.00, laptop 900.00 (Electronics)
    Orders (non-cancelled):
        ann: 2 shirt + 1 laptop  = 920.00  (Jan)
        ann: 1 jeans             =  50.00  (Feb)
        bob: 3 shirt + 1 mouse   =  50.00  (Feb)
        cat: 2 mouse             =  40.00  (Mar)
    Cancelled: cat 5 laptop (must be ignored everywhere)
    """
    p = {
        "shirt": crud.add_product("S", "Shirt", "Clothing", Decimal("10.00"), 100),
        "jeans": crud.add_product("J", "Jeans", "Clothing", Decimal("50.00"), 100),
        "mouse": crud.add_product("M", "Mouse", "Electronics", Decimal("20.00"), 100),
        "laptop": crud.add_product("L", "Laptop", "Electronics", Decimal("900.00"), 100),
    }
    c = {
        "ann": crud.create_customer("Ann", "A", "ann@example.com"),
        "bob": crud.create_customer("Bob", "B", "bob@example.com"),
        "cat": crud.create_customer("Cat", "C", "cat@example.com"),
    }
    place_order(c["ann"], [(p["shirt"], 2), (p["laptop"], 1)], on="2026-01-15")
    place_order(c["ann"], [(p["jeans"], 1)], on="2026-02-10")
    place_order(c["bob"], [(p["shirt"], 3), (p["mouse"], 1)], on="2026-02-20")
    place_order(c["cat"], [(p["mouse"], 2)], on="2026-03-05")
    place_order(c["cat"], [(p["laptop"], 5)], on="2026-03-06", status="cancelled")
    return p, c


def test_top_selling_products_rank_with_ties(store):
    p, _ = store
    rows = analytics.top_selling_products()

    # shirt 5 units, mouse 3, jeans 1, laptop 1 -> jeans and laptop tie at rank 3
    assert [(r["product_id"], r["units_sold"], r["rank"]) for r in rows] == [
        (p["shirt"], 5, 1),
        (p["mouse"], 3, 2),
        (p["jeans"], 1, 3),
        (p["laptop"], 1, 3),
    ]


def test_product_rank_by_category(store):
    p, _ = store
    rows = analytics.product_rank_by_category(top_n=1)

    assert [(r["category"], r["product_id"], r["revenue"]) for r in rows] == [
        ("Clothing", p["shirt"], Decimal("50.00")),  # shirt 50 vs jeans 50 -> tie...
        ("Clothing", p["jeans"], Decimal("50.00")),  # ...so both are rank 1
        ("Electronics", p["laptop"], Decimal("900.00")),
    ]
    electronics = analytics.product_rank_by_category(top_n=2)[-2:]
    assert [r["pct_of_category"] for r in electronics] == [Decimal("93.75"), Decimal("6.25")]


def test_revenue_per_customer(store):
    _, c = store
    rows = analytics.revenue_per_customer()

    assert [(r["customer_id"], r["orders"], r["total_revenue"], r["rank"]) for r in rows] == [
        (c["ann"], 2, Decimal("970.00"), 1),
        (c["bob"], 1, Decimal("50.00"), 2),
        (c["cat"], 1, Decimal("40.00"), 3),  # cancelled 4,500.00 order ignored
    ]
    assert rows[0]["avg_order_value"] == Decimal("485.00")
    assert rows[0]["customer_name"] == "Ann A"


def test_revenue_per_customer_limit(store):
    assert len(analytics.revenue_per_customer(limit=2)) == 2


def test_monthly_revenue_growth_and_running_total(store):
    rows = analytics.monthly_revenue()

    assert [r["month"] for r in rows] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert [r["revenue"] for r in rows] == [Decimal("920.00"), Decimal("100.00"), Decimal("40.00")]
    assert rows[0]["growth_pct"] is None  # no previous month
    assert rows[1]["growth_pct"] == Decimal("-89.13")
    assert rows[2]["running_total"] == Decimal("1060.00")


def test_queries_on_empty_database():
    assert analytics.top_selling_products() == []
    assert analytics.revenue_per_customer() == []
    assert analytics.monthly_revenue() == []
    assert fetch_one("SELECT count(*) FROM orders")[0] == 0
