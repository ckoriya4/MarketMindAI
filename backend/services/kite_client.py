
import os
import json
import threading
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# Preserve Render environment variables.
load_dotenv(ENV_FILE, override=False)


class KiteClientManager:

    def __init__(self):
        self.api_key = ""
        self.api_secret = ""
        self.access_token = ""

        self.kite = None
        self.is_connected = False

        self._lock = threading.RLock()

        self._init_client()

    # --------------------------------------------------
    # LOAD ACCESS TOKEN
    # --------------------------------------------------

    def _load_access_token(self):

        # 1. Render environment variable
        token = os.getenv("KITE_ACCESS_TOKEN", "").strip()

        if token:
            return token

        # 2. Optional token file
        token_file = os.getenv(
            "KITE_TOKEN_FILE",
            "/var/data/kite_access_token.json"
        ).strip()

        if not token_file:
            return ""

        path = Path(token_file)

        if not path.exists():
            return ""

        try:
            content = path.read_text(
                encoding="utf-8"
            ).strip()

            if not content:
                return ""

            try:
                data = json.loads(content)

                if isinstance(data, dict):
                    return str(
                        data.get("access_token", "")
                    ).strip()

                return ""

            except json.JSONDecodeError:
                # Support plain-text token files.
                return content

        except Exception as exc:
            print("[KiteClient] Token file error:", exc)
            return ""

    # --------------------------------------------------
    # INITIALIZE KITE CLIENT
    # --------------------------------------------------

    def _init_client(self):

        with self._lock:

            load_dotenv(ENV_FILE, override=False)

            self.api_key = os.getenv(
                "KITE_API_KEY", ""
            ).strip()

            self.api_secret = os.getenv(
                "KITE_API_SECRET", ""
            ).strip()

            token = self._load_access_token()

            if not self.api_key:
                self.kite = None
                self.access_token = ""
                self.is_connected = False
                print("[KiteClient] API key missing")
                return False

            if not token:
                self.kite = None
                self.access_token = ""
                self.is_connected = False
                print("[KiteClient] Access token missing")
                return False

            return self.set_access_token(token)

    # --------------------------------------------------
    # UPDATE TOKEN AFTER ZERODHA LOGIN
    # --------------------------------------------------

    def set_access_token(self, token):

        token = str(token or "").strip()

        if not token:
            return False

        with self._lock:

            self.api_key = os.getenv(
                "KITE_API_KEY", ""
            ).strip()

            if not self.api_key:
                print("[KiteClient] API key missing")
                return False

            try:
                from kiteconnect import KiteConnect

                client = KiteConnect(
                    api_key=self.api_key,
                    timeout=12
                )

                client.set_access_token(token)

                # Verify token with Zerodha.
                profile = client.profile()

                if not profile or not profile.get("user_id"):
                    raise ValueError(
                        "Invalid Kite profile response"
                    )

                # Activate only after successful verification.
                self.kite = client
                self.access_token = token
                self.is_connected = True

                # Make token available to other backend code.
                os.environ["KITE_ACCESS_TOKEN"] = token

                print(
                    "[KiteClient] Connected as "
                    + str(profile.get("user_id"))
                )

                return True

            except Exception as exc:

                print(
                    "[KiteClient] Token verification failed:",
                    str(exc)
                )

                return False

    # --------------------------------------------------
    # GET STATUS
    # --------------------------------------------------

    def get_status(self):

        with self._lock:

            # Detect a token changed through environment.
            current_token = self._load_access_token()

            if current_token != self.access_token:
                self._init_client()

            return {
                "has_api_key": bool(self.api_key),
                "has_access_token": bool(self.access_token),
                "is_connected": self.is_connected,
                "mode": (
                    "Live Zerodha"
                    if self.is_connected
                    else "Dynamic Simulation Engine"
                )
            }

    # --------------------------------------------------
    # RECONNECT
    # --------------------------------------------------

    def reconnect(self):

        return self._init_client()


# Shared application instance.
kite_manager = KiteClientManager()
