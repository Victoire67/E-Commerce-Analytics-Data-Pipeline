"""Index management and the EXPLAIN ANALYZE benchmark harness."""

from decimal import Decimal

import pytest

from ecommerce_pipeline import benchmark, crud, db
from ecommerce_pipeline.schema import (
    PERFORMANCE_INDEXES,
    create_indexes,
    drop_indexes,
    list_indexes,
)

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture
def small_dataset():
    customer = crud.create_customer("Bench", "Mark", "bench@example.com")
    product = crud.add_product(
        "B-1", "Bench Tee", "Clothing", Decimal("10"), 50, {"colors": ["red"], "sizes": ["XS"]}
    )
    crud.create_order(customer, [(product, 1)])
    return customer


def test_create_and_drop_indexes_are_idempotent():
    with db.get_connection() as conn:
        drop_indexes(conn)
        drop_indexes(conn)
        assert not set(PERFORMANCE_INDEXES) & set(list_indexes(conn))

        create_indexes(conn)
        create_indexes(conn)
        assert set(PERFORMANCE_INDEXES) <= set(list_indexes(conn))


def test_gin_index_is_used_for_containment_when_seq_scan_disabled():
    """With seq scans discouraged, the planner must be able to answer @> from the GIN index."""
    with db.get_connection() as conn:
        create_indexes(conn)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute(
                "EXPLAIN SELECT product_id FROM products "
                """WHERE metadata @> '{"colors": ["red"]}'"""
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
        conn.rollback()
    assert "idx_products_metadata_gin" in plan


def test_measure_returns_timings_and_plan(small_dataset):
    case = benchmark.default_cases(customer_id=small_dataset)[0]

    with db.get_connection() as conn:
        m = benchmark.measure(conn, case, runs=3)

    assert m.median_ms >= 0 and m.min_ms <= m.median_ms
    assert any("orders" in node for node in m.nodes)
    assert "Execution Time" in m.plan_text


def test_run_benchmark_leaves_indexes_in_place_and_renders(small_dataset):
    results, sizes = benchmark.run_benchmark(
        benchmark.default_cases(customer_id=small_dataset), runs=1
    )

    assert len(results) == len(benchmark.default_cases())
    assert set(sizes) == set(PERFORMANCE_INDEXES)
    with db.get_connection() as conn:
        assert set(PERFORMANCE_INDEXES) <= set(list_indexes(conn))

    report = benchmark.render_markdown(results, sizes, runs=1)
    assert report.count("**Before**") == len(results)
    assert "| Speedup |" in report
