"""Benchmark the B-tree and GIN indexes with EXPLAIN ANALYZE.

Drops the performance indexes, measures, applies sql/02_indexes.sql, measures
again, prints a summary and writes the full plans to docs/benchmark_results.md.
Run it after seeding: poetry run python scripts/seed_data.py

Usage:
    poetry run python scripts/benchmark.py
    poetry run python scripts/benchmark.py --runs 15 --customer 42
"""

import argparse
from pathlib import Path

from ecommerce_pipeline.benchmark import default_cases, render_markdown, run_benchmark
from ecommerce_pipeline.db import close_pool, init_pool

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "benchmark_results.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=7, help="measured runs per query")
    parser.add_argument("--customer", type=int, default=5000, help="customer_id to look up")
    args = parser.parse_args()

    init_pool()
    try:
        results, sizes = run_benchmark(default_cases(args.customer), runs=args.runs)
    finally:
        close_pool()

    print(f"{'Query':<55} {'Before':>10} {'After':>10} {'Speedup':>8}")
    for r in results:
        print(
            f"{r.case.key:<55} {r.before.median_ms:>8.3f}ms {r.after.median_ms:>8.3f}ms "
            f"{r.speedup:>7.1f}x"
        )
        print(f"    before: {r.before.access_path}")
        print(f"    after:  {r.after.access_path}")
    print("Index sizes:", sizes)

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(render_markdown(results, sizes, args.runs), encoding="utf-8")
    print(f"Full plans written to {OUTPUT.relative_to(OUTPUT.parents[1])}")


if __name__ == "__main__":
    main()
