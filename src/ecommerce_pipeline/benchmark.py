"""Measure the performance indexes with EXPLAIN ANALYZE (before vs after).

For each query: run it without the indexes, apply sql/02_indexes.sql, run it
again. A single EXPLAIN ANALYZE timing is noisy, so each query is executed once
to warm the cache and then `runs` times, and the median execution time is kept.
"""

import statistics
from dataclasses import dataclass
from typing import Any

from psycopg2 import sql
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json

from ecommerce_pipeline.db import get_connection
from ecommerce_pipeline.schema import PERFORMANCE_INDEXES, create_indexes, drop_indexes

SAMPLE_CUSTOMER_ID = 5000


@dataclass(frozen=True)
class QueryCase:
    key: str
    title: str
    index: str
    query: str
    params: tuple


@dataclass
class Measurement:
    median_ms: float
    min_ms: float
    buffers: int  # shared buffers hit + read: pages the query touched
    nodes: list[str]  # plan nodes, e.g. "Index Scan using idx_x on orders"
    plan_text: str

    @property
    def access_path(self) -> str:
        """The scan node(s) only — what changes when an index is added."""
        return ", ".join(n for n in self.nodes if "Scan" in n) or self.nodes[0]


@dataclass
class CaseResult:
    case: QueryCase
    before: Measurement
    after: Measurement

    @property
    def speedup(self) -> float:
        return self.before.median_ms / self.after.median_ms if self.after.median_ms else 0.0


def default_cases(customer_id: int = SAMPLE_CUSTOMER_ID) -> list[QueryCase]:
    return [
        QueryCase(
            key="orders_by_customer",
            title="Orders of one customer",
            index="idx_orders_customer_id",
            query=(
                "SELECT order_id, order_date, status FROM orders "
                "WHERE customer_id = %s ORDER BY order_date DESC"
            ),
            params=(customer_id,),
        ),
        QueryCase(
            key="customer_order_history",
            title="get_customer_orders() (orders + items + products)",
            index="idx_orders_customer_id",
            query=(
                "SELECT o.order_id, o.order_date, o.status, oi.product_id, p.name, "
                "oi.quantity, oi.unit_price "
                "FROM orders o JOIN order_items oi USING (order_id) "
                "JOIN products p USING (product_id) "
                "WHERE o.customer_id = %s ORDER BY o.order_date DESC, o.order_id DESC"
            ),
            params=(customer_id,),
        ),
        QueryCase(
            key="jsonb_brand_warranty",
            title='metadata @> {"brand": "Voltix", "warranty_months": 36}',
            index="idx_products_metadata_gin",
            query="SELECT product_id, sku, name FROM products WHERE metadata @> %s",
            params=(Json({"brand": "Voltix", "warranty_months": 36}),),
        ),
        QueryCase(
            key="jsonb_clothing_filter",
            title='metadata @> {"colors": ["red"], "sizes": ["XS"], "material": "leather"}',
            index="idx_products_metadata_gin",
            query="SELECT product_id, sku, name FROM products WHERE metadata @> %s",
            params=(Json({"colors": ["red"], "sizes": ["XS"], "material": "leather"}),),
        ),
        QueryCase(
            key="jsonb_key_exists",
            title="metadata ? 'warranty_months' (low selectivity, ~17% of rows)",
            index="idx_products_metadata_gin",
            query="SELECT product_id, sku, name FROM products WHERE metadata ? %s",
            params=("warranty_months",),
        ),
    ]


def _plan_nodes(node: dict[str, Any]) -> list[str]:
    label = node["Node Type"]
    if "Index Name" in node:
        label += f" using {node['Index Name']}"
    if "Relation Name" in node:
        label += f" on {node['Relation Name']}"
    nodes = [label]
    for child in node.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


def explain_json(conn: PgConnection, query: str, params: tuple) -> dict[str, Any]:
    """Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and return the parsed plan."""
    statement = sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ") + sql.SQL(query)
    with conn.cursor() as cur:
        cur.execute(statement, params)
        plan = cur.fetchone()[0][0]
    conn.rollback()  # EXPLAIN ANALYZE really executes the query; end its transaction
    return plan


def explain_text(conn: PgConnection, query: str, params: tuple) -> str:
    """Human-readable EXPLAIN ANALYZE output, as psql would print it."""
    statement = sql.SQL("EXPLAIN (ANALYZE, BUFFERS) ") + sql.SQL(query)
    with conn.cursor() as cur:
        cur.execute(statement, params)
        text = "\n".join(row[0] for row in cur.fetchall())
    conn.rollback()
    return text


def measure(conn: PgConnection, case: QueryCase, runs: int = 7) -> Measurement:
    explain_json(conn, case.query, case.params)  # warm-up: load pages into shared buffers
    plans = [explain_json(conn, case.query, case.params) for _ in range(runs)]
    times = [p["Execution Time"] for p in plans]
    root = plans[-1]["Plan"]
    return Measurement(
        median_ms=statistics.median(times),
        min_ms=min(times),
        buffers=root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0),
        nodes=_plan_nodes(root),
        plan_text=explain_text(conn, case.query, case.params),
    )


def index_sizes(conn: PgConnection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) "
            "FROM pg_indexes WHERE indexname = ANY(%s)",
            (list(PERFORMANCE_INDEXES),),
        )
        sizes = dict(cur.fetchall())
    conn.rollback()
    return sizes


def run_benchmark(
    cases: list[QueryCase] | None = None, runs: int = 7
) -> tuple[list[CaseResult], dict[str, str]]:
    """Drop the indexes, measure, create them, measure again. Leaves indexes in place."""
    cases = cases or default_cases()
    with get_connection() as conn:
        drop_indexes(conn)
        before = [measure(conn, case, runs) for case in cases]
        create_indexes(conn)
        after = [measure(conn, case, runs) for case in cases]
        sizes = index_sizes(conn)
    results = [CaseResult(c, b, a) for c, b, a in zip(cases, before, after, strict=True)]
    return results, sizes


def render_markdown(results: list[CaseResult], sizes: dict[str, str], runs: int) -> str:
    """Summary table plus full before/after plans, ready to paste into docs."""
    lines = [
        "# Benchmark results",
        "",
        f"Median of {runs} `EXPLAIN (ANALYZE, BUFFERS)` runs after one warm-up run. "
        "Buffers = 8 kB pages touched.",
        "",
        "| Query | Index | Before: plan | Before (ms) | After: plan | After (ms) | Speedup "
        "| Buffers before → after |",
        "|---|---|---|---:|---|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.case.title} | `{r.case.index}` | {r.before.access_path} "
            f"| {r.before.median_ms:.3f} | {r.after.access_path} | {r.after.median_ms:.3f} "
            f"| {r.speedup:.1f}× | {r.before.buffers} → {r.after.buffers} |"
        )
    lines += ["", "Index sizes: " + ", ".join(f"`{k}` {v}" for k, v in sorted(sizes.items()))]
    for r in results:
        lines += [
            "",
            f"## {r.case.title}",
            "",
            "```sql",
            r.case.query,
            "```",
            "",
            "**Before**",
            "",
            "```",
            r.before.plan_text,
            "```",
            "",
            "**After**",
            "",
            "```",
            r.after.plan_text,
            "```",
        ]
    return "\n".join(lines) + "\n"
