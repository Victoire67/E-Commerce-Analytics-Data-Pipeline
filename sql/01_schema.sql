-- =============================================================================
-- E-Commerce Analytics Data Pipeline — schema (DDL), Third Normal Form
-- =============================================================================
-- Every non-key column depends on the key, the whole key, and nothing but the key:
--   * category names live in `categories`, not repeated on every product row;
--   * order totals are NOT stored — they are derived from order_items;
--   * order_items.unit_price is the price *at time of purchase* (a historical
--     fact about the order line), not a copy of products.price.
--
-- NOTE: there is intentionally no index on orders.customer_id here.
-- PostgreSQL does not index foreign-key columns automatically; that index is
-- added in 02_indexes.sql so its effect can be measured with EXPLAIN ANALYZE.
-- =============================================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name   VARCHAR(100) NOT NULL,
    last_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(255) NOT NULL,
    phone        VARCHAR(30),
    country      VARCHAR(100),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_customers_email UNIQUE (email),
    CONSTRAINT ck_customers_email_format CHECK (email LIKE '%_@_%')
);

CREATE TABLE IF NOT EXISTS categories (
    category_id  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    description  TEXT,
    CONSTRAINT uq_categories_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS products (
    product_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku             VARCHAR(50)    NOT NULL,
    name            VARCHAR(255)   NOT NULL,
    category_id     INTEGER        NOT NULL REFERENCES categories (category_id) ON DELETE RESTRICT,
    price           NUMERIC(10, 2) NOT NULL,
    stock_quantity  INTEGER        NOT NULL DEFAULT 0,
    -- Flexible, per-category attributes (sizes, colors, specs...). See README.
    metadata        JSONB          NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT uq_products_sku UNIQUE (sku),
    CONSTRAINT ck_products_price_non_negative CHECK (price >= 0),
    CONSTRAINT ck_products_stock_non_negative CHECK (stock_quantity >= 0),
    CONSTRAINT ck_products_metadata_is_object CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS orders (
    order_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id  BIGINT      NOT NULL REFERENCES customers (customer_id) ON DELETE RESTRICT,
    order_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',
    CONSTRAINT ck_orders_status CHECK (
        status IN ('pending', 'paid', 'shipped', 'delivered', 'cancelled')
    )
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id    BIGINT         NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id  BIGINT         NOT NULL REFERENCES products (product_id) ON DELETE RESTRICT,
    quantity    INTEGER        NOT NULL,
    unit_price  NUMERIC(10, 2) NOT NULL,
    PRIMARY KEY (order_id, product_id),
    CONSTRAINT ck_order_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT ck_order_items_unit_price_non_negative CHECK (unit_price >= 0)
);
