import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class KiteClientManager:
    def __init__(self):
        self.api_key = os.getenv("KITE_API_KEY", "").strip()
        self.api_secret = os.getenv("KITE_API_SECRET", "").strip()
        self.access_token = os.getenv("KITE_ACCESS_TOKEN", "").strip()
        self.kite = None
        self.is_connected = False
        self._init_client()

    def _init_client(self):
        # Reload env in case token was just updated
        load_dotenv(BASE_DIR / ".env", override=True)
        self.api_key = os.getenv("KITE_API_KEY", "").strip()
        self.api_secret = os.getenv("KITE_API_SECRET", "").strip()
        self.access_token = os.getenv("KITE_ACCESS_TOKEN", "").strip()

        if self.api_key and self.access_token:
            try:
                from kiteconnect import KiteConnect
                client = KiteConnect(api_key=self.api_key)
                client.set_access_token(self.access_token)
                # Verify session with a lightweight call (e.g. profile)
                profile = client.profile()
                if profile and "user_id" in profile:
                    self.kite = client
                    self.is_connected = True
                    print(f"[KiteClient] Connected as {profile.get('user_id')}")
                    return
            except Exception as e:
                print(f"[KiteClient] Connection warning: {e}. Running in Dynamic Engine mode.")
                self.is_connected = False
                self.kite = None
        else:
            self.is_connected = False
            self.kite = None

    def get_status(self):
        self._init_client()
        return {
            "has_api_key": bool(self.api_key),
            "has_access_token": bool(self.access_token),
            "is_connected": self.is_connected,
            "mode": "Live Zerodha" if self.is_connected else "Dynamic Simulation Engine"
        }

kite_manager = KiteClientManager()

