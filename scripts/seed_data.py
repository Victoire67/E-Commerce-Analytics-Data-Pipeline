"""Load a large, reproducible sample dataset into PostgreSQL.

WARNING: wipes all pipeline tables first.

Usage:
    poetry run python scripts/seed_data.py                # 10k customers, 20k products, 100k orders
    poetry run python scripts/seed_data.py --orders 20000 # smaller/faster
"""

import argparse

from ecommerce_pipeline.db import close_pool, init_pool
from ecommerce_pipeline.seed import seed_all


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--customers", type=int, default=10_000)
    parser.add_argument("--products", type=int, default=20_000)
    parser.add_argument("--orders", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    args = parser.parse_args()

    init_pool()
    try:
        result = seed_all(args.customers, args.products, args.orders, args.seed)
    finally:
        close_pool()

    print(
        f"Seeded {result.customers:,} customers, {result.products:,} products, "
        f"{result.orders:,} orders, {result.order_items:,} order items "
        f"in {result.seconds:.1f}s"
    )


if __name__ == "__main__":
    main()
