"""Redis cache for the top-10 best-selling products (cache-aside pattern).

    read:  Redis hit?  -> return cached JSON
           Redis miss? -> run the PostgreSQL ranking query, store it with a TTL, return it
    write: a new order changes the ranking -> delete the key (next read rebuilds it)

PostgreSQL stays the source of truth; Redis only holds a disposable copy. If the
cache is lost or stale, the worst case is one slower query, never wrong data
for longer than the TTL.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import redis

from ecommerce_pipeline.analytics import top_selling_products
from ecommerce_pipeline.config import Settings, load_settings

TOP_PRODUCTS_KEY = "ecommerce:top_products:{limit}"
DEFAULT_TTL_SECONDS = 300


@dataclass
class CachedResult:
    products: list[dict[str, Any]]
    from_cache: bool


def get_redis(settings: Settings | None = None) -> redis.Redis:
    """Create a Redis client; decode_responses returns str instead of bytes."""
    settings = settings or load_settings()
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )


def _to_json(value: Any) -> Any:
    # Decimal is not JSON-serializable; keep money exact by sending it as a string.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def get_top_products(
    client: redis.Redis, limit: int = 10, ttl: int = DEFAULT_TTL_SECONDS
) -> CachedResult:
    """Return the top `limit` best sellers, from Redis when possible."""
    key = TOP_PRODUCTS_KEY.format(limit=limit)
    cached = client.get(key)
    if cached is not None:
        return CachedResult(products=json.loads(cached), from_cache=True)

    payload = json.dumps(top_selling_products(limit), default=_to_json)
    # SET with EX writes the value and its expiry atomically.
    client.set(key, payload, ex=ttl)
    # Return the same JSON shape a cache hit would, so callers see one format.
    return CachedResult(products=json.loads(payload), from_cache=False)


def invalidate_top_products(client: redis.Redis) -> int:
    """Drop every cached top-N list (call after orders change). Returns keys deleted."""
    keys = list(client.scan_iter(match=TOP_PRODUCTS_KEY.format(limit="*")))
    return client.delete(*keys) if keys else 0


def cache_ttl(client: redis.Redis, limit: int = 10) -> int:
    """Seconds until the cached list expires (-2 if absent)."""
    return client.ttl(TOP_PRODUCTS_KEY.format(limit=limit))
