"""Create the PostgreSQL tables for the pipeline.

Usage:
    poetry run python scripts/create_tables.py           # create (idempotent)
    poetry run python scripts/create_tables.py --reset   # drop everything, then create
    poetry run python scripts/create_tables.py --indexes # also apply sql/02_indexes.sql
"""

import argparse

import psycopg2

from ecommerce_pipeline.config import load_settings
from ecommerce_pipeline.schema import (
    create_indexes,
    create_tables,
    drop_tables,
    list_indexes,
    list_tables,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="drop all tables before creating")
    parser.add_argument(
        "--indexes", action="store_true", help="also create the performance indexes"
    )
    args = parser.parse_args()

    conn = psycopg2.connect(load_settings().postgres_dsn)
    try:
        if args.reset:
            drop_tables(conn)
            print("Dropped existing tables.")
        create_tables(conn)
        print("Tables:", ", ".join(list_tables(conn)))
        if args.indexes:
            create_indexes(conn)
            print("Indexes:", ", ".join(list_indexes(conn)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
