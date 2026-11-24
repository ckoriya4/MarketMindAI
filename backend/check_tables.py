
from services.database import get_db_connection

with get_db_connection() as conn:
    rows = conn.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """).fetchall()

print("PostgreSQL tables:")
for row in rows:
    print("-", row["table_name"])

print("Total tables:", len(rows))
