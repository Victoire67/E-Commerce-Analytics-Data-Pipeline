-- =============================================================================
-- Performance indexes. Kept separate from 01_schema.sql so their effect can be
-- measured: scripts/benchmark.py runs EXPLAIN ANALYZE without them, applies this
-- file, and measures again. See README "Optimization report".
-- =============================================================================

-- B-tree on the foreign key orders.customer_id.
-- PostgreSQL indexes primary keys and UNIQUE columns automatically, but NOT
-- foreign-key columns. Without this, "orders of customer X" (get_customer_orders,
-- revenue per customer) reads the whole orders table.
CREATE INDEX IF NOT EXISTS idx_orders_customer_id
    ON orders USING btree (customer_id);

-- GIN on the JSONB metadata column.
-- A GIN (Generalized Inverted iNdex) stores every key and value inside each
-- document and points back to the rows containing it — like a book's index.
-- The default jsonb_ops operator class supports @> (containment) and the key
-- operators ?, ?| and ?& used by product_metadata.py. (jsonb_path_ops would be
-- smaller and faster, but supports @> only.)
CREATE INDEX IF NOT EXISTS idx_products_metadata_gin
    ON products USING gin (metadata);

-- Refresh planner statistics so the new indexes are considered immediately.
ANALYZE orders;
ANALYZE products;
