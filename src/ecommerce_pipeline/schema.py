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
