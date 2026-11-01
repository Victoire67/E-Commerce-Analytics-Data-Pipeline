# Loom demo script (~7 minutes)

Before recording: `docker compose up -d`, then run the demo once so the dataset is seeded
and warm. Record with the terminal and VS Code side by side.

| Time | Show | Say |
|---|---|---|
| 0:00 | README top, architecture diagram | "An e-commerce analytics pipeline. PostgreSQL is the source of truth, JSONB holds flexible product attributes, Redis caches best sellers, MongoDB holds sessions and carts. Each store holds the data it fits best." |
| 0:45 | `docker compose ps`, `docker-compose.yml` | "All three databases run in Docker with healthchecks and volumes; credentials come from `.env`." |
| 1:15 | ER diagram + `sql/01_schema.sql` | "3NF: categories are their own table, order totals are derived not stored. `unit_price` on order items is the price at purchase, which is history, not duplication. Constraints enforce non-negative stock and prices, valid statuses and unique emails." |
| 2:00 | `poetry run python scripts/run_demo.py --skip-benchmark` → sections 1–3 | "Connections come from a pool. `create_order()` is one transaction: it locks the product rows with `FOR UPDATE`, checks stock, inserts, and decrements stock. Watch: ordering 5 when 1 is left raises an error and nothing changes. The SQL-injection string is stored as plain text because every query is parameterized." |
| 3:15 | Section 4 (JSONB) | "`@>` containment finds red XS leather products; `||` patches metadata without rewriting it." |
| 3:45 | Section 5 (Redis) | "Cache-aside: the first read misses and runs the RANK() query in PostgreSQL, about 225 ms. The second is a Redis hit in under 1 ms. The key expires after 5 minutes." |
| 4:20 | Section 6 (MongoDB → checkout) | "An anonymous session builds a cart; adding the same product merges the line. After login, checkout turns the cart into a PostgreSQL order, clears the cart, and invalidates the Redis cache." |
| 5:00 | Section 7 (analytics) | "RANK with PARTITION BY ranks products inside each category. Chained CTEs build revenue per customer step by step. LAG gives month-over-month growth." |
| 5:40 | `poetry run python scripts/benchmark.py` + README optimization report | "Without an index, finding one customer's orders is a sequential scan of 812 pages. PostgreSQL doesn't index foreign keys automatically. With the B-tree it reads 12 pages: 4.5 ms to 0.06 ms. The GIN index makes selective JSONB queries about 8× faster. For a key that matches 17% of rows the gain is small, so indexes pay off for selective queries." |
| 6:40 | `poetry run pytest -q`, CI badge | "68 tests against the real databases, including rollback and a concurrency test where five buyers race for three items. CI runs them on every push." |
