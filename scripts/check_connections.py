"""Smoke test: verify PostgreSQL, Redis and MongoDB are reachable.

Usage: poetry run python scripts/check_connections.py
"""

import psycopg2
import redis
from pymongo import MongoClient

from ecommerce_pipeline.config import load_settings


def main() -> None:
    settings = load_settings()

    conn = psycopg2.connect(settings.postgres_dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        print("PostgreSQL OK:", cur.fetchone()[0].split(",")[0])
    conn.close()

    r = redis.Redis(host=settings.redis_host, port=settings.redis_port)
    print("Redis OK:", r.ping())

    mongo = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)
    print("MongoDB OK:", mongo.admin.command("ping"))
    mongo.close()


if __name__ == "__main__":
    main()
