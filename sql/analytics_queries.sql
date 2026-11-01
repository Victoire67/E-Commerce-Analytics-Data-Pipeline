-- =============================================================================
-- Analytical queries (window functions + CTEs). Run directly in psql:
--   docker exec -i ecommerce-postgres psql -U ecommerce_user -d ecommerce < sql/analytics_queries.sql
-- The same queries are exposed in Python by src/ecommerce_pipeline/analytics.py.
-- Cancelled orders are excluded from every sales figure.
-- =============================================================================

-- 1. Top 10 best-selling products by units sold — RANK() (ties share a rank,
--    the next rank is skipped: 1, 2, 2, 4). This is the list cached in Redis.
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
       p.product_id, p.sku, p.name, c.name AS category, ps.units_sold, ps.revenue
FROM product_sales ps
JOIN products p   USING (product_id)
JOIN categories c USING (category_id)
ORDER BY rank, p.product_id
LIMIT 10;


-- 2. Top 3 products per category by revenue — RANK() OVER (PARTITION BY ...)
--    restarts the ranking in each category; SUM() OVER gives each product's share.
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
           ROUND(100.0 * revenue / SUM(revenue) OVER (PARTITION BY category), 2) AS pct_of_category
    FROM product_revenue
)
SELECT category, category_rank, product_id, name, units_sold, revenue, pct_of_category
FROM ranked
WHERE category_rank <= 3          -- window results can only be filtered one level up
ORDER BY category, category_rank, product_id;


-- 3. Revenue per customer — chained CTEs: order totals -> customer totals -> ranking.
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
LIMIT 10;


-- 4. Monthly revenue with month-over-month growth (LAG) and running total.
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
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS growth_pct,
       SUM(revenue) OVER (ORDER BY month) AS running_total
FROM monthly
ORDER BY month;


-- 5. JSONB metadata examples (fast with the GIN index from 02_indexes.sql).
SELECT product_id, name, metadata -> 'colors' AS colors, metadata -> 'sizes' AS sizes
FROM products
WHERE metadata @> '{"colors": ["red"], "sizes": ["M"]}'
ORDER BY product_id
LIMIT 10;

SELECT metadata ->> 'brand' AS brand, COUNT(*) AS products
FROM products
WHERE metadata ? 'brand'
GROUP BY 1
ORDER BY products DESC;
