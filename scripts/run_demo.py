"""End-to-end demo of the whole pipeline (designed to be narrated in the Loom video).

Usage:
    poetry run python scripts/run_demo.py                  # uses existing data (seeds if empty)
    poetry run python scripts/run_demo.py --fresh          # recreate tables and reseed first
    poetry run python scripts/run_demo.py --skip-benchmark # skip the EXPLAIN ANALYZE step
"""

import argparse
import time
import uuid
from collections.abc import Sequence
from decimal import Decimal

from psycopg2 import sql

from ecommerce_pipeline import analytics, cache, crud, db
from ecommerce_pipeline import product_metadata as pm
from ecommerce_pipeline.benchmark import run_benchmark
from ecommerce_pipeline.checkout import checkout
from ecommerce_pipeline.schema import create_tables, drop_tables, list_tables
from ecommerce_pipeline.seed import seed_all
from ecommerce_pipeline.sessions import SessionStore


def section(number: int, title: str) -> None:
    print(f"\n{'=' * 78}\n {number}. {title}\n{'=' * 78}")


def table(rows: Sequence[dict], columns: Sequence[str]) -> None:
    """Print rows as an aligned text table."""
    if not rows:
        print("  (no rows)")
        return
    cells = [[str(row.get(col, "")) for col in columns] for row in rows]
    widths = [max(len(col), *(len(r[i]) for r in cells)) for i, col in enumerate(columns)]
    print("  " + "  ".join(col.ljust(w) for col, w in zip(columns, widths, strict=True)))
    print("  " + "  ".join("-" * w for w in widths))
    for r in cells:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)))


def count(table_name: str) -> int:
    # Identifiers can't be %s parameters; sql.Identifier quotes them safely.
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name)))
        return cur.fetchone()[0]


def setup(fresh: bool) -> None:
    section(1, "Schema (3NF) and data")
    with db.get_connection() as conn:
        if fresh:
            drop_tables(conn)
        create_tables(conn)
        print("  Tables:", ", ".join(list_tables(conn)))
    if fresh or count("orders") == 0:
        print("  Seeding 10k customers, 20k products, 100k orders ...")
        result = seed_all()
        print(f"  Done in {result.seconds:.1f}s ({result.order_items:,} order items)")
    print(
        f"  customers={count('customers'):,}  products={count('products'):,}  "
        f"orders={count('orders'):,}"
    )


def demo_crud() -> tuple[int, int]:
    section(2, "CRUD with psycopg2 (pooled connections, parameterized queries)")
    tag = uuid.uuid4().hex[:6]
    customer_id = crud.create_customer(
        "Demo", "Customer", f"demo.{tag}@example.com", country="Rwanda"
    )
    product_id = crud.add_product(
        f"DEMO-{tag}",
        "Demo Hoodie",
        "Clothing",
        Decimal("45.00"),
        stock_quantity=3,
        metadata={"colors": ["red", "black"], "sizes": ["M", "L"], "material": "cotton"},
    )
    print(f"  create_customer() -> customer_id={customer_id}")
    print(f"  add_product()     -> product_id={product_id} (stock 3, JSONB metadata)")

    order_id = crud.create_order(customer_id, [(product_id, 2)])
    print(f"  create_order(2 hoodies) -> order_id={order_id}")
    for order in crud.get_customer_orders(customer_id):
        print(f"  get_customer_orders(): order {order['order_id']} total={order['total']}")
        table(order["items"], ["product_id", "product_name", "quantity", "unit_price"])
    print(f"  stock now: {crud.get_product(product_id)['stock_quantity']}")
    return customer_id, product_id


def demo_transactions(customer_id: int, product_id: int) -> None:
    section(3, "ACID transaction: a failing order rolls back completely")
    before_orders = len(crud.get_customer_orders(customer_id))
    try:
        crud.create_order(customer_id, [(product_id, 5)])  # only 1 left
    except crud.InsufficientStockError as exc:
        print(f"  InsufficientStockError: {exc}")
    after_orders = len(crud.get_customer_orders(customer_id))
    stock = crud.get_product(product_id)["stock_quantity"]
    print(f"  orders before/after: {before_orders}/{after_orders}, stock still {stock}")

    payload = "x'); DROP TABLE customers; --"
    injected = crud.create_customer(payload, "Tables", f"bobby.{uuid.uuid4().hex[:6]}@example.com")
    stored = crud.get_customer(injected)["first_name"]
    print(f"  SQL injection payload stored as plain text: {stored!r}")
    print(f"  customers table still has {count('customers'):,} rows")


def demo_jsonb(product_id: int) -> None:
    section(4, "PostgreSQL JSONB product metadata")
    criteria = {"colors": ["red"], "sizes": ["XS"], "material": "leather"}
    rows = pm.find_products_by_metadata(criteria, limit=5)
    print(f"  metadata @> {criteria}  (first 5)")
    table(rows, ["product_id", "name", "category", "price"])
    print("  Brands (metadata ->> 'brand'):")
    table(pm.count_products_by_attribute("brand"), ["value", "products"])
    merged = pm.merge_product_metadata(product_id, {"limited_edition": True})
    print(f"  metadata || patch -> {merged}")


def demo_redis() -> None:
    section(5, "Redis cache-aside: top-10 best sellers")
    client = cache.get_redis()
    cache.invalidate_top_products(client)
    for attempt in ("1st read", "2nd read"):
        started = time.perf_counter()
        result = cache.get_top_products(client)
        elapsed = (time.perf_counter() - started) * 1000
        source = "Redis HIT" if result.from_cache else "MISS -> PostgreSQL"
        print(f"  {attempt}: {source:<20} {elapsed:8.2f} ms")
    print(f"  TTL remaining: {cache.cache_ttl(client)} s")
    table(result.products, ["rank", "product_id", "name", "category", "units_sold"])


def demo_mongo(customer_id: int) -> None:
    section(6, "MongoDB sessions and carts -> checkout")
    sessions = SessionStore.from_settings()
    client = cache.get_redis()
    best_sellers = [p["product_id"] for p in cache.get_top_products(client).products[:2]]

    session_id = sessions.create_session(device={"os": "android", "app": "1.4.2"})
    print(f"  anonymous session {session_id}")
    sessions.add_to_cart(session_id, best_sellers[0], 1)
    sessions.add_to_cart(session_id, best_sellers[1], 2)
    cart = sessions.add_to_cart(session_id, best_sellers[0], 1)  # merges into the same line
    table(cart, ["product_id", "quantity"])
    sessions.attach_customer(session_id, customer_id)
    print(f"  logged in as customer {customer_id}; cart kept")

    order_id = checkout(sessions, client, session_id)
    print(f"  checkout() -> PostgreSQL order {order_id}; cart now {sessions.get_cart(session_id)}")
    from_cache = cache.get_top_products(client).from_cache
    print(f"  Redis cache invalidated: next read from cache? {from_cache}")
    sessions.end_session(session_id)


def demo_analytics() -> None:
    section(7, "Analytics: window functions and CTEs")
    print("  Top product per category  (RANK() OVER (PARTITION BY category))")
    table(
        analytics.product_rank_by_category(top_n=1),
        ["category", "category_rank", "name", "revenue", "pct_of_category"],
    )
    print("\n  Revenue per customer  (chained CTEs + RANK())")
    table(
        analytics.revenue_per_customer(limit=5),
        ["rank", "customer_name", "country", "orders", "total_revenue", "avg_order_value"],
    )
    print("\n  Monthly revenue, last 6 months  (LAG() + running SUM())")
    table(analytics.monthly_revenue()[-6:], ["month", "orders", "revenue", "growth_pct"])


def demo_benchmark() -> None:
    section(8, "EXPLAIN ANALYZE: B-tree and GIN indexes, before vs after")
    results, sizes = run_benchmark(runs=5)
    for r in results:
        print(
            f"  {r.case.key:<24} {r.before.median_ms:7.3f} ms -> {r.after.median_ms:7.3f} ms "
            f"({r.speedup:5.1f}x)  pages {r.before.buffers} -> {r.after.buffers}"
        )
        print(f"      {r.before.access_path}  ->  {r.after.access_path}")
    print(f"  index sizes: {sizes}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fresh", action="store_true", help="recreate tables and reseed")
    parser.add_argument("--skip-benchmark", action="store_true")
    args = parser.parse_args()

    db.init_pool()
    try:
        setup(args.fresh)
        customer_id, product_id = demo_crud()
        demo_transactions(customer_id, product_id)
        demo_jsonb(product_id)
        demo_redis()
        demo_mongo(customer_id)
        demo_analytics()
        if not args.skip_benchmark:
            demo_benchmark()
    finally:
        db.close_pool()
    print("\nDemo complete.")


if __name__ == "__main__":
    main()
