
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Load backend environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / "backend" / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL missing. Check backend/.env"
    )

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

migration_file = (
    BASE_DIR / "backend" / "migrations"
    / "001_auth_notifications.sql"
)

if not migration_file.exists():
    raise FileNotFoundError(
        f"Migration file not found: {migration_file}"
    )

sql = migration_file.read_text(encoding="utf-8")

print("Connecting to PostgreSQL...")

with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)

    conn.commit()

print("Migration executed successfully!")

# Verify tables
with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN (
                'mm_users',
                'mm_auth_otps',
                'mm_signal_outbox',
                'mm_notification_deliveries'
            )
            ORDER BY table_name
        """)

        tables = cur.fetchall()

print("\nDatabase tables found:")

for table in tables:
    print("-", table[0])

if len(tables) == 4:
    print("\nSUCCESS: All four tables are ready.")
else:
    print("\nWARNING: Some tables are missing.")
