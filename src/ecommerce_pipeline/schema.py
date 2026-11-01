"""Create and drop the PostgreSQL schema from the SQL files in sql/."""

from pathlib import Path

from psycopg2.extensions import connection as PgConnection

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
SCHEMA_FILE = SQL_DIR / "01_schema.sql"

# Child tables first, so foreign keys never block a drop.
TABLES = ("order_items", "orders", "products", "categories", "customers")


def create_tables(conn: PgConnection) -> None:
    """Run 01_schema.sql inside a single transaction (all tables or none)."""
    ddl = SCHEMA_FILE.read_text(encoding="utf-8")
    with conn, conn.cursor() as cur:
        cur.execute(ddl)


def drop_tables(conn: PgConnection) -> None:
    """Drop every pipeline table. Destructive — used by --reset and tests."""
    with conn, conn.cursor() as cur:
        for table in TABLES:
            # Table names come from the fixed TABLES tuple, never from user input.
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")  # noqa: S608


def list_tables(conn: PgConnection) -> list[str]:
    """Return the names of the tables in the public schema."""
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        return [row[0] for row in cur.fetchall()]


INDEXES_FILE = SQL_DIR / "02_indexes.sql"
PERFORMANCE_INDEXES = ("idx_orders_customer_id", "idx_products_metadata_gin")


def create_indexes(conn: PgConnection) -> None:
    """Apply 02_indexes.sql (B-tree on orders.customer_id, GIN on products.metadata)."""
    sql_text = INDEXES_FILE.read_text(encoding="utf-8")
    with conn, conn.cursor() as cur:
        cur.execute(sql_text)


def drop_indexes(conn: PgConnection) -> None:
    """Remove the performance indexes (used to measure the 'before' state)."""
    with conn, conn.cursor() as cur:
        for index in PERFORMANCE_INDEXES:
            # Names come from the fixed PERFORMANCE_INDEXES tuple, never user input.
            cur.execute(f"DROP INDEX IF EXISTS {index}")  # noqa: S608
        cur.execute("ANALYZE orders")
        cur.execute("ANALYZE products")


def list_indexes(conn: PgConnection) -> list[str]:
    """Names of all indexes in the public schema."""
    with conn, conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")
        return [row[0] for row in cur.fetchall()]
