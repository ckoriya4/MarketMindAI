
import os
import threading
from pathlib import Path

import psycopg
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


class KiteClientManager:
    def __init__(self):
        self.api_key = ""
        self.api_secret = ""
        self.database_url = ""
        self.access_token = ""
        self.kite = None
        self.is_connected = False
        self.profile = None
        self._lock = threading.RLock()

        self._init_client()

    def _load_config(self):
        load_dotenv(BASE_DIR / ".env", override=False)

        self.api_key = os.getenv("KITE_API_KEY", "").strip()
        self.api_secret = os.getenv("KITE_API_SECRET", "").strip()
        self.database_url = os.getenv("DATABASE_URL", "").strip()

        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql://", 1
            )

    def _connect_db(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not configured.")

        return psycopg.connect(
            self.database_url,
            connect_timeout=10,
        )

    def _ensure_table(self):
        with self._connect_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kite_sessions (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    access_token TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

    def _load_access_token(self):
        try:
            self._ensure_table()

            with self._connect_db() as conn:
                row = conn.execute("""
                    SELECT access_token
                    FROM kite_sessions
                    WHERE id = 1
                """).fetchone()

            return row[0].strip() if row and row[0] else ""

        except Exception as exc:
            print("[KiteClient] Database token load failed:", str(exc))
            return ""

    def _save_access_token(self, token):
        self._ensure_table()

        with self._connect_db() as conn:
            conn.execute("""
                INSERT INTO kite_sessions (id, access_token, updated_at)
                VALUES (1, %s, NOW())
                ON CONFLICT (id)
                DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    updated_at = NOW()
            """, (token,))

        print("[KiteClient] Access token saved to PostgreSQL.")

    def _delete_access_token(self):
        self._ensure_table()

        with self._connect_db() as conn:
            conn.execute("""
                DELETE FROM kite_sessions WHERE id = 1
            """)

    def _clear_connection(self):
        self.kite = None
        self.access_token = ""
        self.is_connected = False
        self.profile = None

    def _init_client(self):
        with self._lock:
            self._load_config()

            if not self.api_key:
                self._clear_connection()
                print("[KiteClient] KITE_API_KEY missing.")
                return False

            if not self.database_url:
                self._clear_connection()
                print("[KiteClient] DATABASE_URL missing.")
                return False

            token = self._load_access_token()

            if not token:
                self._clear_connection()
                print("[KiteClient] No saved Kite access token.")
                return False

            return self.set_access_token(token)

    def set_access_token(self, token):
        token = str(token or "").strip()

        with self._lock:
            self._load_config()

            if not self.api_key or not self.database_url or not token:
                self._clear_connection()
                print("[KiteClient] Missing API key, database URL or token.")
                return False

            try:
                from kiteconnect import KiteConnect

                client = KiteConnect(
                    api_key=self.api_key,
                    timeout=15,
                )
                client.set_access_token(token)

                # Verify the token with Zerodha before saving it.
                profile = client.profile()

                if not isinstance(profile, dict) or not profile.get("user_id"):
                    raise ValueError("Invalid Kite profile response.")

                # Save token before marking the manager connected.
                self._save_access_token(token)

                self.kite = client
                self.access_token = token
                self.is_connected = True
                self.profile = profile

                print(
                    "[KiteClient] Connected as "
                    + str(profile.get("user_id"))
                )
                return True

            except Exception as exc:
                self._clear_connection()
                print("[KiteClient] Token verification/save failed:", str(exc))
                return False

    def get_status(self):
        with self._lock:
            self._load_config()
            current_token = self._load_access_token()

            if current_token != self.access_token:
                if current_token:
                    self.set_access_token(current_token)
                else:
                    self._clear_connection()

            return {
                "has_api_key": bool(self.api_key),
                "has_access_token": bool(self.access_token),
                "is_connected": self.is_connected,
                "mode": (
                    "Live Zerodha"
                    if self.is_connected
                    else "Login required"
                ),
                "user_id": (
                    self.profile.get("user_id")
                    if self.profile else None
                ),
            }

    def reconnect(self):
        return self._init_client()

    def logout(self):
        with self._lock:
            try:
                self._load_config()
                self._delete_access_token()
                print("[KiteClient] PostgreSQL token deleted.")
            except Exception as exc:
                print("[KiteClient] Token deletion failed:", str(exc))
                return False

            self._clear_connection()
            return True


kite_manager = KiteClientManager()
