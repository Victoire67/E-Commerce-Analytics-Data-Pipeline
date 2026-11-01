"""Query and update the JSONB `products.metadata` column.

JSONB operators used here (all GIN-indexable with the default jsonb_ops class):
    @>   containment:   metadata @> '{"colors": ["red"]}'  -> has red among its colors
    ?    key exists:    metadata ? 'warranty_months'
    ?|   any key:       metadata ?| array['sizes', 'colors']
    ->>  extract text:  metadata ->> 'brand'
    ||   merge objects (used to patch metadata without rewriting it)
"""

from collections.abc import Mapping, Sequence
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from ecommerce_pipeline.db import transaction


def find_products_by_metadata(criteria: Mapping[str, Any], limit: int = 50) -> list[dict]:
    """Products whose metadata contains `criteria` (JSONB containment, @>).

    Arrays match by inclusion: {"colors": ["red"]} matches ["red", "blue"].
    Nested objects work too: {"specs": {"wireless": True}}.
    """
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.product_id, p.sku, p.name, c.name AS category, p.price,
                   p.stock_quantity, p.metadata
            FROM products p JOIN categories c USING (category_id)
            WHERE p.metadata @> %s
            ORDER BY p.product_id
            LIMIT %s
            """,
            (Json(dict(criteria)), limit),
        )
        return cur.fetchall()


def find_products_with_any_key(keys: Sequence[str], limit: int = 50) -> list[dict]:
    """Products whose metadata has at least one of `keys` (?| operator)."""
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.product_id, p.sku, p.name, c.name AS category, p.price,
                   p.stock_quantity, p.metadata
            FROM products p JOIN categories c USING (category_id)
            WHERE p.metadata ?| %s
            ORDER BY p.product_id
            LIMIT %s
            """,
            (list(keys), limit),
        )
        return cur.fetchall()


def count_products_by_attribute(key: str) -> list[dict]:
    """How many products share each value of a top-level text attribute (e.g. 'brand')."""
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT metadata ->> %s AS value, count(*) AS products
            FROM products
            WHERE metadata ? %s
            GROUP BY 1
            ORDER BY products DESC, value
            """,
            (key, key),
        )
        return cur.fetchall()


def available_colors() -> list[dict]:
    """Distinct colors across the catalogue with product counts (unnests a JSONB array)."""
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT color, count(*) AS products
            FROM products, jsonb_array_elements_text(metadata -> 'colors') AS color
            GROUP BY color
            ORDER BY products DESC, color
            """
        )
        return cur.fetchall()


def merge_product_metadata(product_id: int, patch: Mapping[str, Any]) -> dict | None:
    """Merge `patch` into a product's metadata (top-level keys overwrite) and return the result."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE products
            SET metadata = metadata || %s, updated_at = now()
            WHERE product_id = %s
            RETURNING metadata
            """,
            (Json(dict(patch)), product_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def remove_metadata_key(product_id: int, key: str) -> dict | None:
    """Delete one top-level key from a product's metadata (the - operator)."""
    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE products
            SET metadata = metadata - %s, updated_at = now()
            WHERE product_id = %s
            RETURNING metadata
            """,
            (key, product_id),
        )
        row = cur.fetchone()
        return row[0] if row else None
