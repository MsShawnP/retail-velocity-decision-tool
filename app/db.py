"""Database connection for the Cinderhaven Data Platform (Postgres)."""

import os

import psycopg2
import psycopg2.extensions

DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values,
    'DEC2FLOAT',
    lambda value, curs: float(value) if value is not None else None,
)
psycopg2.extensions.register_type(DEC2FLOAT)


class ConnectionWrapper:
    """Wraps psycopg2 to provide SQLite-compatible con.execute().fetchone() pattern.

    Also proxies cursor() so pd.read_sql works transparently.
    """

    def __init__(self, dsn: str):
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = True

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def cursor(self):
        return self._conn.cursor()

    def close(self):
        self._conn.close()


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and configure."
        )
    return url
