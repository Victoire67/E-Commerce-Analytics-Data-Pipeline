"""Bulk-generate realistic sample data with Faker.

The volume matters: on a few hundred rows PostgreSQL prefers sequential scans
no matter what, so index improvements only become measurable with tens of
thousands of orders.

Historical orders are bulk-loaded with execute_values (one round trip per page
of rows) rather than through crud.create_order(); they represent already
fulfilled orders, so stock is not decremented for them.
"""

import random
import time
from dataclasses import dataclass
from decimal import Decimal

from faker import Faker
from psycopg2.extras import Json, execute_values

from ecommerce_pipeline.db import transaction

BATCH_SIZE = 5_000

# Per-category product nouns and a metadata generator, so JSONB varies by category.
CATEGORIES: dict[str, dict] = {
    "Clothing": {
        "nouns": ["T-Shirt", "Hoodie", "Jeans", "Jacket", "Dress", "Sneakers", "Cap"],
        "price": (9, 150),
    },
    "Electronics": {
        "nouns": ["Headphones", "Smartwatch", "Speaker", "Keyboard", "Mouse", "Charger"],
        "price": (15, 900),
    },
    "Home & Kitchen": {
        "nouns": ["Mug", "Blender", "Pan", "Knife Set", "Lamp", "Cushion"],
        "price": (5, 300),
    },
    "Books": {
        "nouns": ["Novel", "Cookbook", "Biography", "Guide", "Anthology"],
        "price": (6, 60),
    },
    "Sports": {
        "nouns": ["Yoga Mat", "Dumbbell", "Football", "Water Bottle", "Racket"],
        "price": (8, 250),
    },
    "Beauty": {
        "nouns": ["Moisturizer", "Perfume", "Lipstick", "Shampoo", "Face Mask"],
        "price": (4, 120),
    },
}
ADJECTIVES = ["Classic", "Premium", "Eco", "Urban", "Pro", "Essential", "Deluxe", "Smart", "Retro"]
COLORS = ["black", "white", "red", "blue", "green", "grey", "navy", "beige"]
SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
BRANDS = ["Nordline", "Voltix", "Acorn", "Helio", "Kestrel", "Orbis"]
MATERIALS = ["cotton", "polyester", "wool", "denim", "leather", "linen"]
ORDER_STATUSES = ["delivered", "shipped", "paid", "pending", "cancelled"]
STATUS_WEIGHTS = [70, 10, 8, 7, 5]


@dataclass
class SeedResult:
    customers: int
    products: int
    orders: int
    order_items: int
    seconds: float


def _metadata(category: str, rng: random.Random, fake: Faker) -> dict:
    """Build category-specific product attributes for the JSONB column."""
    if category == "Clothing":
        return {
            "colors": rng.sample(COLORS, k=rng.randint(1, 4)),
            "sizes": rng.sample(SIZES, k=rng.randint(2, 5)),
            "material": rng.choice(MATERIALS),
        }
    if category == "Electronics":
        return {
            "brand": rng.choice(BRANDS),
            "warranty_months": rng.choice([6, 12, 24, 36]),
            "specs": {"wireless": rng.random() < 0.6, "battery_hours": rng.randint(4, 60)},
            "colors": rng.sample(COLORS[:4], k=rng.randint(1, 2)),
        }
    if category == "Books":
        return {
            "author": fake.name(),
            "pages": rng.randint(90, 900),
            "format": rng.choice(["paperback", "hardcover", "ebook"]),
            "language": rng.choice(["en", "fr", "es"]),
        }
    return {
        "brand": rng.choice(BRANDS),
        "colors": rng.sample(COLORS, k=rng.randint(1, 3)),
        "eco_friendly": rng.random() < 0.3,
    }


def truncate_all() -> None:
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE order_items, orders, products, categories, customers "
            "RESTART IDENTITY CASCADE"
        )


def seed_customers(count: int, fake: Faker) -> list[int]:
    rows = [
        (
            fake.first_name(),
            fake.last_name(),
            f"customer{i}.{fake.user_name()}@{fake.free_email_domain()}",
            fake.phone_number()[:30],
            fake.country()[:100],
            fake.date_time_between(start_date="-3y", end_date="-2y", tzinfo=None),
        )
        for i in range(1, count + 1)
    ]
    with transaction() as conn, conn.cursor() as cur:
        result = execute_values(
            cur,
            "INSERT INTO customers (first_name, last_name, email, phone, country, created_at) "
            "VALUES %s RETURNING customer_id",
            rows,
            page_size=BATCH_SIZE,
            fetch=True,
        )
    return [row[0] for row in result]


def seed_products(count: int, fake: Faker, rng: random.Random) -> list[tuple[int, Decimal]]:
    """Insert categories and `count` products; return [(product_id, price), ...]."""
    with transaction() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO categories (name, description) VALUES %s",
            [(name, f"{name} products") for name in CATEGORIES],
        )
        cur.execute("SELECT name, category_id FROM categories")
        category_ids = dict(cur.fetchall())

        rows = []
        for i in range(1, count + 1):
            category = rng.choice(list(CATEGORIES))
            spec = CATEGORIES[category]
            noun = rng.choice(spec["nouns"])
            low, high = spec["price"]
            rows.append(
                (
                    f"{category[:3].upper()}-{i:05d}",
                    f"{rng.choice(ADJECTIVES)} {noun}",
                    category_ids[category],
                    Decimal(rng.uniform(low, high)).quantize(Decimal("0.01")),
                    rng.randint(50, 1_000),
                    Json(_metadata(category, rng, fake)),
                )
            )
        result = execute_values(
            cur,
            "INSERT INTO products (sku, name, category_id, price, stock_quantity, metadata) "
            "VALUES %s RETURNING product_id, price",
            rows,
            page_size=BATCH_SIZE,
            fetch=True,
        )
    return [(row[0], row[1]) for row in result]


def seed_orders(
    count: int,
    customer_ids: list[int],
    products: list[tuple[int, Decimal]],
    fake: Faker,
    rng: random.Random,
) -> int:
    """Insert `count` orders with 1-4 lines each, in batches. Returns lines inserted.

    Popularity is skewed (a few customers and products dominate) so that
    rankings and best-seller lists look like real store data.
    """
    customer_weights = [1 / (rank + 1) ** 0.5 for rank in range(len(customer_ids))]
    product_weights = [1 / (rank + 1) ** 0.8 for rank in range(len(products))]
    total_items = 0

    for start in range(0, count, BATCH_SIZE):
        batch = min(BATCH_SIZE, count - start)
        orders = [
            (
                customer_id,
                fake.date_time_between(start_date="-2y", end_date="now", tzinfo=None),
                rng.choices(ORDER_STATUSES, STATUS_WEIGHTS)[0],
            )
            for customer_id in rng.choices(customer_ids, customer_weights, k=batch)
        ]
        with transaction() as conn, conn.cursor() as cur:
            order_ids = execute_values(
                cur,
                "INSERT INTO orders (customer_id, order_date, status) VALUES %s "
                "RETURNING order_id",
                orders,
                page_size=BATCH_SIZE,
                fetch=True,
            )
            items = []
            for (order_id,) in order_ids:
                lines = {pid: price for pid, price in rng.choices(products, product_weights, k=4)}
                for product_id, price in list(lines.items())[: rng.randint(1, 4)]:
                    items.append((order_id, product_id, rng.randint(1, 3), price))
            execute_values(
                cur,
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES %s",
                items,
                page_size=BATCH_SIZE,
            )
        total_items += len(items)
    return total_items


def analyze() -> None:
    """Refresh planner statistics so EXPLAIN reflects the new data."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("ANALYZE")


def seed_all(
    customers: int = 10_000,
    products: int = 500,
    orders: int = 100_000,
    seed: int = 42,
) -> SeedResult:
    """Wipe the tables and load a full, reproducible dataset."""
    started = time.perf_counter()
    rng = random.Random(seed)  # noqa: S311 - reproducible test data, not security
    Faker.seed(seed)
    fake = Faker()

    truncate_all()
    customer_ids = seed_customers(customers, fake)
    product_rows = seed_products(products, fake, rng)
    item_count = seed_orders(orders, customer_ids, product_rows, fake, rng)
    analyze()

    return SeedResult(
        customers=len(customer_ids),
        products=len(product_rows),
        orders=orders,
        order_items=item_count,
        seconds=time.perf_counter() - started,
    )
