
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in backend/.env")

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version(), current_database()")
            version, database = cur.fetchone()

    print("PostgreSQL connection successful!")
    print("Database:", database)
    print("Version:", version.split(",")[0])

except Exception as e:
    print("PostgreSQL connection failed.")
    print("Error:", str(e))
