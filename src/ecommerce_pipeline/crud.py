"""CRUD operations for customers, products and orders.

Every query uses %s placeholders: psycopg2 sends values separately from the SQL
text, so user input can never change the structure of a query (no SQL injection).
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from ecommerce_pipeline.db import transaction


class OrderError(Exception):
    """Base class for order-processing failures."""


class CustomerNotFoundError(OrderError):
    pass


class ProductNotFoundError(OrderError):
    pass


class InsufficientStockError(OrderError):
    pass


# --- Customers ----------------------------------------------------------------


def create_customer(
    first_name: str,
    last_name: str,
    email: str,
    phone: str | None = None,
    country: str | None = None,
) -> int:
    """Insert a customer and return its generated customer_id."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customers (first_name, last_name, email, phone, country)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING customer_id
            """,
            (first_name, last_name, email, phone, country),
        )
        return cur.fetchone()[0]


def get_customer(customer_id: int) -> dict[str, Any] | None:
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM customers WHERE customer_id = %s", (customer_id,))
        return cur.fetchone()


# --- Products -----------------------------------------------------------------


def get_or_create_category(name: str, description: str | None = None) -> int:
    """Return the category_id for `name`, creating the category if needed."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO categories (name, description) VALUES (%s, %s)
            ON CONFLICT (name) DO NOTHING
            RETURNING category_id
            """,
            (name, description),
        )
        row = cur.fetchone()
        if row is None:  # already existed
            cur.execute("SELECT category_id FROM categories WHERE name = %s", (name,))
            row = cur.fetchone()
        return row[0]


def add_product(
    sku: str,
    name: str,
    category: str,
    price: Decimal | float,
    stock_quantity: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> int:
    """Insert a product (creating its category if new) and return its product_id.

    `metadata` is stored as JSONB, e.g. {"colors": ["red"], "sizes": ["M", "L"]}.
    """
    category_id = get_or_create_category(category)
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products (sku, name, category_id, price, stock_quantity, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING product_id
            """,
            (sku, name, category_id, price, stock_quantity, Json(dict(metadata or {}))),
        )
        return cur.fetchone()[0]


def get_product(product_id: int) -> dict[str, Any] | None:
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.*, c.name AS category
            FROM products p
            JOIN categories c USING (category_id)
            WHERE p.product_id = %s
            """,
            (product_id,),
        )
        return cur.fetchone()


def update_product(
    product_id: int,
    *,
    price: Decimal | float | None = None,
    stock_quantity: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Update the given fields of a product. Returns False if it doesn't exist.

    COALESCE keeps the current value for any field passed as None, so the SQL
    text stays fixed and fully parameterized.
    """
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE products
            SET price          = COALESCE(%s, price),
                stock_quantity = COALESCE(%s, stock_quantity),
                metadata       = COALESCE(%s, metadata),
                updated_at     = now()
            WHERE product_id = %s
            """,
            (
                price,
                stock_quantity,
                Json(dict(metadata)) if metadata is not None else None,
                product_id,
            ),
        )
        return cur.rowcount == 1


def delete_product(product_id: int) -> bool:
    """Delete a product. Raises ForeignKeyViolation if it appears in any order."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
        return cur.rowcount == 1


# --- Orders -------------------------------------------------------------------


def create_order(customer_id: int, items: Iterable[tuple[int, int]]) -> int:
    """Place an order atomically and return its order_id.

    `items` is an iterable of (product_id, quantity). In ONE transaction:
      1. verify the customer exists;
      2. lock the product rows (SELECT ... FOR UPDATE) so concurrent orders
         can't both buy the last unit;
      3. check every product exists and has enough stock;
      4. insert the order and its lines, capturing the current price;
      5. decrement stock.
    If any step fails, everything is rolled back — no partial orders, no
    stock changes (ACID).
    """
    quantities: dict[int, int] = {}
    for product_id, quantity in items:
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive (product {product_id}: {quantity})")
        quantities[product_id] = quantities.get(product_id, 0) + quantity
    if not quantities:
        raise ValueError("An order needs at least one item")

    product_ids = sorted(quantities)  # fixed lock order prevents deadlocks

    with transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM customers WHERE customer_id = %s", (customer_id,))
        if cur.fetchone() is None:
            raise CustomerNotFoundError(f"Customer {customer_id} does not exist")

        cur.execute(
            """
            SELECT product_id, price, stock_quantity
            FROM products
            WHERE product_id = ANY(%s)
            ORDER BY product_id
            FOR UPDATE
            """,
            (product_ids,),
        )
        products = {pid: (price, stock) for pid, price, stock in cur.fetchall()}

        missing = [pid for pid in product_ids if pid not in products]
        if missing:
            raise ProductNotFoundError(f"Products not found: {missing}")
        for pid in product_ids:
            available = products[pid][1]
            if available < quantities[pid]:
                raise InsufficientStockError(
                    f"Product {pid}: requested {quantities[pid]}, only {available} in stock"
                )

        cur.execute(
            "INSERT INTO orders (customer_id) VALUES (%s) RETURNING order_id",
            (customer_id,),
        )
        order_id = cur.fetchone()[0]

        cur.executemany(
            """
            INSERT INTO order_items (order_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
            """,
            [(order_id, pid, quantities[pid], products[pid][0]) for pid in product_ids],
        )
        cur.executemany(
            """
            UPDATE products
            SET stock_quantity = stock_quantity - %s, updated_at = now()
            WHERE product_id = %s
            """,
            [(quantities[pid], pid) for pid in product_ids],
        )
        return order_id


def update_order_status(order_id: int, status: str) -> bool:
    """Change an order's status (validated by the ck_orders_status constraint)."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = %s WHERE order_id = %s", (status, order_id))
        return cur.rowcount == 1


def get_customer_orders(customer_id: int) -> list[dict[str, Any]]:
    """Return a customer's orders (newest first), each with its line items and total."""
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.status,
                   oi.product_id, p.name AS product_name, oi.quantity, oi.unit_price
            FROM orders o
            JOIN order_items oi USING (order_id)
            JOIN products p USING (product_id)
            WHERE o.customer_id = %s
            ORDER BY o.order_date DESC, o.order_id DESC, oi.product_id
            """,
            (customer_id,),
        )
        rows = cur.fetchall()

    orders: dict[int, dict[str, Any]] = {}
    for row in rows:
        order = orders.setdefault(
            row["order_id"],
            {
                "order_id": row["order_id"],
                "order_date": row["order_date"],
                "status": row["status"],
                "items": [],
                "total": Decimal("0"),
            },
        )
        order["items"].append(
            {
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "quantity": row["quantity"],
                "unit_price": row["unit_price"],
            }
        )
        order["total"] += row["quantity"] * row["unit_price"]
    return list(orders.values())
