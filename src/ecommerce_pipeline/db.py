"""PostgreSQL connection pooling and transaction helpers.

Opening a PostgreSQL connection costs a TCP handshake, authentication and a new
backend process. The pool keeps a few connections open and lends them out, so
each operation only pays for the query itself.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg2.extensions import connection as PgConnection
from psycopg2.pool import ThreadedConnectionPool

from ecommerce_pipeline.config import Settings, load_settings

_pool: ThreadedConnectionPool | None = None


def init_pool(settings: Settings | None = None, minconn: int = 1, maxconn: int = 10) -> None:
    """Create the global pool. Safe to call more than once (later calls are no-ops)."""
    global _pool
    if _pool is None:
        settings = settings or load_settings()
        _pool = ThreadedConnectionPool(minconn, maxconn, dsn=settings.postgres_dsn)


def close_pool() -> None:
    """Close every pooled connection (call on application shutdown)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_connection() -> Iterator[PgConnection]:
    """Borrow a connection from the pool and always give it back."""
    if _pool is None:
        init_pool()
    assert _pool is not None
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


@contextmanager
def transaction() -> Iterator[PgConnection]:
    """Run a block of work atomically: COMMIT on success, ROLLBACK on any exception.

    Usage:
        with transaction() as conn, conn.cursor() as cur:
            cur.execute(...)
            cur.execute(...)
    """
    with get_connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
