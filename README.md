# E-Commerce Analytics Data Pipeline

Data processing and analytics pipeline for a fictional e-commerce store, built on
PostgreSQL (3NF schema + JSONB), Redis (best-seller cache), and MongoDB (sessions/carts).

## Setup

Requires Python 3.11+ and [Poetry](https://python-poetry.org/) 2.x.

```bash
poetry install          # creates .venv/ and installs all dependencies
poetry run pytest       # run the test suite
```

`requirements.txt` is generated from the lock file for non-Poetry users:

```bash
poetry export -f requirements.txt --without-hashes -o requirements.txt
```
