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

## Development

```bash
poetry run pytest       # run the test suite
poetry run ruff check . # lint
```

`requirements.txt` is generated from the lock file for non-Poetry users:

```bash
poetry export -f requirements.txt --without-hashes -o requirements.txt
```
