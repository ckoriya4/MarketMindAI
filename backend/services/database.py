
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from pathlib import Path


# ---------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------

BASE = Path(__file__).resolve().parents[1]

load_dotenv(BASE / ".env", override=False)


# ---------------------------------------------------------
# DATABASE URL
# ---------------------------------------------------------

def get_database_url():

    url = os.getenv("DATABASE_URL", "").strip()

    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. "
            "Configure DATABASE_URL in Render Environment "
            "or backend/.env for local development."
        )

    # Render PostgreSQL URLs may use postgres://.
    # psycopg accepts postgresql://.
    if url.startswith("postgres://"):
        url = url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    return url


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

@contextmanager
def get_db_connection():
    """
    Shared PostgreSQL connection.

    Automatically:
    - Opens connection
    - Uses dictionary rows
    - Commits successful transactions
    - Rolls back failed transactions
    - Closes connection
    """

    conn = None

    try:

        conn = psycopg.connect(
            get_database_url(),
            connect_timeout=15,
            row_factory=dict_row
        )

        yield conn

        conn.commit()

    except Exception:

        if conn is not None:
            conn.rollback()

        raise

    finally:

        if conn is not None:
            conn.close()


# ---------------------------------------------------------
# DATABASE HEALTH TEST
# ---------------------------------------------------------

def test_database():

    with get_db_connection() as conn:

        row = conn.execute(
            """
            SELECT
                current_database() AS database,
                current_timestamp AS server_time
            """
        ).fetchone()

        return {
            "database": row["database"],
            "server_time": row["server_time"]
        }


# ---------------------------------------------------------
# AUTH TABLE CHECK
# ---------------------------------------------------------

def check_auth_tables():

    required_tables = [
        "mm_users",
        "mm_auth_otps",
        "mm_signal_outbox",
        "mm_notification_deliveries"
    ]

    with get_db_connection() as conn:

        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = ANY(%s)
            """,
            (required_tables,)
        ).fetchall()

        existing = {
            row["table_name"]
            for row in rows
        }

        missing = [
            table
            for table in required_tables
            if table not in existing
        ]

        return {
            "existing_tables": sorted(existing),
            "missing_tables": missing,
            "ready": len(missing) == 0
        }
