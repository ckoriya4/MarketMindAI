
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()


def get_database_url():
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Check backend/.env"
        )

    return url


@contextmanager
def get_db_connection():
    """
    Shared PostgreSQL connection.
    Use this function in backend services.
    """
    conn = psycopg.connect(
        get_database_url(),
        connect_timeout=15,
        row_factory=dict_row
    )

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def test_database():
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT current_database() AS database"
        ).fetchone()

        return row["database"]
