"""Analytical SQL queries (window functions and CTEs).

The SQL is kept in sync with sql/analytics_queries.sql, which holds the same
queries for running directly in psql. Cancelled orders never count as sales.
"""

from psycopg2.extras import RealDictCursor

from ecommerce_pipeline.db import transaction


def top_selling_products(limit: int = 10) -> list[dict]:
    """Best sellers by units sold, ranked with RANK() (ties share a rank)."""
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH product_sales AS (
                SELECT oi.product_id,
                       SUM(oi.quantity)                 AS units_sold,
                       SUM(oi.quantity * oi.unit_price) AS revenue
                FROM order_items oi
                JOIN orders o USING (order_id)
                WHERE o.status <> 'cancelled'
                GROUP BY oi.product_id
            )
            SELECT RANK() OVER (ORDER BY ps.units_sold DESC) AS rank,
                   p.product_id, p.sku, p.name, c.name AS category, p.price,
                   ps.units_sold, ps.revenue
            FROM product_sales ps
            JOIN products p USING (product_id)
            JOIN categories c USING (category_id)
            ORDER BY rank, p.product_id
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def product_rank_by_category(top_n: int = 3) -> list[dict]:
    """Top `top_n` products by revenue *within each category*.

    RANK() OVER (PARTITION BY ...) restarts the ranking for every category.
    The window result can't be filtered in the same SELECT's WHERE clause
    (windows are computed after WHERE), so the ranking is wrapped in a CTE.
    """
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH product_revenue AS (
                SELECT p.product_id, p.name, c.name AS category,
                       SUM(oi.quantity)                 AS units_sold,
                       SUM(oi.quantity * oi.unit_price) AS revenue
                FROM order_items oi
                JOIN orders o     USING (order_id)
                JOIN products p   USING (product_id)
                JOIN categories c USING (category_id)
                WHERE o.status <> 'cancelled'
                GROUP BY p.product_id, p.name, c.name
            ),
            ranked AS (
                SELECT *,
                       RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS category_rank,
                       ROUND(100.0 * revenue / SUM(revenue) OVER (PARTITION BY category), 2)
                           AS pct_of_category
                FROM product_revenue
            )
            SELECT category, category_rank, product_id, name, units_sold, revenue,
                   pct_of_category
            FROM ranked
            WHERE category_rank <= %s
            ORDER BY category, category_rank, product_id
            """,
            (top_n,),
        )
        return cur.fetchall()


def revenue_per_customer(limit: int = 10) -> list[dict]:
    """Customers ranked by lifetime revenue, built up in readable CTE steps.

    1. order_totals      - one row per (non-cancelled) order with its total
    2. customer_revenue  - totals rolled up per customer
    3. final SELECT      - joins names, ranks, and computes average order value
    """
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH order_totals AS (
                SELECT o.order_id, o.customer_id, o.order_date,
                       SUM(oi.quantity * oi.unit_price) AS order_total
                FROM orders o
                JOIN order_items oi USING (order_id)
                WHERE o.status <> 'cancelled'
                GROUP BY o.order_id, o.customer_id, o.order_date
            ),
            customer_revenue AS (
                SELECT customer_id,
                       COUNT(*)         AS orders,
                       SUM(order_total) AS total_revenue,
                       MAX(order_date)  AS last_order_date
                FROM order_totals
                GROUP BY customer_id
            )
            SELECT RANK() OVER (ORDER BY cr.total_revenue DESC) AS rank,
                   c.customer_id,
                   c.first_name || ' ' || c.last_name AS customer_name,
                   c.country,
                   cr.orders,
                   cr.total_revenue,
                   ROUND(cr.total_revenue / cr.orders, 2) AS avg_order_value,
                   cr.last_order_date
            FROM customer_revenue cr
            JOIN customers c USING (customer_id)
            ORDER BY rank, c.customer_id
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def monthly_revenue() -> list[dict]:
    """Revenue per month with month-over-month growth (LAG) and a running total."""
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH monthly AS (
                SELECT date_trunc('month', o.order_date)::date AS month,
                       COUNT(DISTINCT o.order_id)              AS orders,
                       SUM(oi.quantity * oi.unit_price)        AS revenue
                FROM orders o
                JOIN order_items oi USING (order_id)
                WHERE o.status <> 'cancelled'
                GROUP BY 1
            )
            SELECT month, orders, revenue,
                   LAG(revenue) OVER (ORDER BY month) AS previous_revenue,
                   ROUND(
                       100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
                       / NULLIF(LAG(revenue) OVER (ORDER BY month), 0),
                       2
                   ) AS growth_pct,
                   SUM(revenue) OVER (ORDER BY month) AS running_total
            FROM monthly
            ORDER BY month
            """
        )
        return cur.fetchall()
