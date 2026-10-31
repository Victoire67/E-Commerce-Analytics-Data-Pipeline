# E-Commerce Analytics Data Pipeline

Data processing and analytics pipeline for a fictional e-commerce store, built on
PostgreSQL (3NF schema + JSONB), Redis (best-seller cache), and MongoDB (sessions/carts).

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) 2.x
- Docker Desktop (Docker Compose v2)

## Setup

```bash
# 1. Install Python dependencies into .venv/
poetry install

# 2. Create your local environment file and set real passwords
cp .env.example .env

# 3. Start PostgreSQL, Redis and MongoDB
docker compose up -d
docker compose ps        # wait until all three show "(healthy)"

# 4. Verify Python can reach all three services
poetry run python scripts/check_connections.py
```

| Service    | Image              | Host port (default) | Used for                          |
|------------|--------------------|---------------------|-----------------------------------|
| PostgreSQL | `postgres:16-alpine` | 5432              | Customers, products, orders (3NF) |
| Redis      | `redis:7-alpine`   | 6379                | Top-10 best-seller cache          |
| MongoDB    | `mongo:7`          | 27017               | User sessions and carts           |

Useful commands: `docker compose logs <service>`, `docker compose down` (stop, keep data),
`docker compose down -v` (stop and delete all data).

## Loading data

```bash
poetry run python scripts/create_tables.py          # create schema (add --reset to recreate)
poetry run python scripts/seed_data.py              # 10k customers, 500 products, 100k orders
```

The seeder ([src/ecommerce_pipeline/seed.py](src/ecommerce_pipeline/seed.py)) uses Faker with a
fixed seed, so every run produces the same dataset. Rows are bulk-inserted with
`execute_values` in batches of 5,000 (~30 s for the full dataset). Popularity is skewed so a few
customers and products dominate, like real store data, and `metadata` differs per category
(sizes/colors/material for clothing, brand/warranty/specs for electronics, author/pages for books).
The large volume is deliberate: on a few hundred rows PostgreSQL always uses a sequential scan, so
index improvements are only measurable at scale.

For a small, readable dataset instead, load the hand-written SQL file:

```bash
docker exec -i ecommerce-postgres psql -U ecommerce_user -d ecommerce < sql/03_sample_data.sql
```

## Python API (CRUD)

All database access goes through a `ThreadedConnectionPool`
([db.py](src/ecommerce_pipeline/db.py)); `transaction()` commits on success and rolls back on any
exception. Every query in [crud.py](src/ecommerce_pipeline/crud.py) is parameterized (`%s`), so
input is never interpolated into SQL.

```python
from ecommerce_pipeline import crud

customer_id = crud.create_customer("Amina", "Uwase", "amina@example.com", country="Rwanda")
shirt = crud.add_product("CLO-1", "T-Shirt", "Clothing", 19.99, stock_quantity=10,
                         metadata={"colors": ["red"], "sizes": ["M", "L"]})
order_id = crud.create_order(customer_id, [(shirt, 2)])
crud.get_customer_orders(customer_id)   # orders with line items and computed totals
```

`create_order()` is a single ACID transaction: it locks the product rows
(`SELECT ... FOR UPDATE`, in a fixed order to avoid deadlocks), checks the customer, products and
stock, inserts the order and its lines at the current price, and decrements stock. Any failure
(`InsufficientStockError`, `ProductNotFoundError`, `CustomerNotFoundError`) rolls back everything,
so partial orders and overselling are impossible.

## Database Design

### ER diagram

```mermaid
erDiagram
    CUSTOMERS ||--o{ ORDERS : places
    ORDERS ||--|{ ORDER_ITEMS : contains
    PRODUCTS ||--o{ ORDER_ITEMS : "appears in"
    CATEGORIES ||--o{ PRODUCTS : groups

    CUSTOMERS {
        bigint customer_id PK
        varchar first_name
        varchar last_name
        varchar email UK
        varchar phone
        varchar country
        timestamptz created_at
    }
    CATEGORIES {
        int category_id PK
        varchar name UK
        text description
    }
    PRODUCTS {
        bigint product_id PK
        varchar sku UK
        varchar name
        int category_id FK
        numeric price
        int stock_quantity
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }
    ORDERS {
        bigint order_id PK
        bigint customer_id FK
        timestamptz order_date
        varchar status
    }
    ORDER_ITEMS {
        bigint order_id PK, FK
        bigint product_id PK, FK
        int quantity
        numeric unit_price
    }
```

Create the tables with `poetry run python scripts/create_tables.py` (add `--reset` to drop and
recreate). The DDL lives in [sql/01_schema.sql](sql/01_schema.sql).

### Normalization decisions (3NF)

| Rule | How the schema satisfies it |
|------|-----------------------------|
| **1NF** — atomic values, no repeating groups | An order's products are rows in `order_items`, not a list column on `orders`. |
| **2NF** — no partial dependency on a composite key | `order_items` has key `(order_id, product_id)`; `quantity` and `unit_price` depend on both. Product name/category depend only on `product_id`, so they stay in `products`. |
| **3NF** — no transitive dependencies | Category name/description depend on the category, not the product, so they live in `categories`. Customer details live only in `customers`; `orders` references them by `customer_id`. |

Deliberate choices:

- **`order_items.unit_price` is not duplication.** It records the price *when the order was
  placed*; `products.price` is the current price. Without it, a price change would rewrite
  historical revenue.
- **Order totals are not stored.** A total is `SUM(quantity * unit_price)` over the order's
  lines; storing it would create a value that can drift out of sync.
- **`products.metadata` is JSONB.** Attributes differ per category (sizes/colors for clothing,
  specs/warranty for electronics). Modelling each as a column would leave most columns NULL;
  an EAV table would make every read a pivot. JSONB keeps them queryable (and GIN-indexable)
  while the core, always-present fields stay relational.

### Constraints

- Identity primary keys on every table; composite PK on `order_items`.
- Foreign keys: `ON DELETE RESTRICT` for customers/products/categories (history can't be
  orphaned); `ON DELETE CASCADE` from `orders` to `order_items` (lines belong to their order).
- `UNIQUE` on `customers.email`, `products.sku`, `categories.name`.
- `CHECK`: price/unit_price ≥ 0, stock ≥ 0, quantity > 0, order status in a fixed set,
  basic email shape, metadata must be a JSON object.

## Development

```bash
poetry run pytest       # run the test suite (needs `docker compose up -d`)
poetry run ruff check . # lint
```

Tests run against a separate `ecommerce_test` database that is created automatically, rebuilt
once per session and truncated before each test, so your seeded data is never touched. They
cover CRUD, constraint violations, SQL-injection safety, transaction rollback, concurrent
ordering without overselling, and the seed generator.

`requirements.txt` is generated from the lock file for non-Poetry users:

```bash
poetry export -f requirements.txt --without-hashes -o requirements.txt
```
