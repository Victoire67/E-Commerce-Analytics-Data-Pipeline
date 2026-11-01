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
