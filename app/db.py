"""Database connection for the Cinderhaven Data Platform (Postgres).

Fork-safe connection pool: each PID gets its own ThreadedConnectionPool so
gunicorn pre-fork workers don't share sockets. pd.read_sql needs a raw
psycopg2 connection (not a cursor), hence the separate get_raw_conn().
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extensions
import psycopg2.pool

# ============================================================
# Decimal -> float typecast (registered per-pool creation)
# ============================================================

DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values,
    'DEC2FLOAT',
    lambda value, curs: float(value) if value is not None else None,
)


def _register_dec2float() -> None:
    """Register the DEC2FLOAT typecast globally for the current process."""
    psycopg2.extensions.register_type(DEC2FLOAT)


# ============================================================
# PID-aware pool management
# ============================================================

_pools: dict[int, psycopg2.pool.ThreadedConnectionPool] = {}


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and configure."
        )
    return url


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return a ThreadedConnectionPool for the current PID, creating one if needed."""
    pid = os.getpid()
    pool = _pools.get(pid)
    if pool is None:
        _register_dec2float()
        pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=get_database_url(),
        )
        _pools[pid] = pool
    return pool


@contextmanager
def get_conn():
    """Context manager that checks out a connection and returns it on exit.

    Usage::

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    pool = get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        pool.putconn(conn)


def get_raw_conn():
    """Return a raw psycopg2 connection for pd.read_sql.

    The caller is responsible for returning it via ``get_pool().putconn(conn)``
    when finished, or — more commonly — used inside a ``with get_conn()`` block
    where the context manager handles cleanup. For one-shot pd.read_sql calls
    that live outside a ``with`` block, the connection will be returned to the
    pool on garbage collection, but explicit return is preferred.
    """
    pool = get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    return conn
