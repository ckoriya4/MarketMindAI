
import os
import json
import threading
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# Preserve environment variables configured on Render.
load_dotenv(ENV_FILE, override=False)


class KiteClientManager:

    def __init__(self):
        self.api_key = ""
        self.api_secret = ""
        self.access_token = ""

        self.kite = None
        self.is_connected = False
        self.profile = None

        self._lock = threading.RLock()

        self._init_client()

    # --------------------------------------------------
    # LOAD ACCESS TOKEN
    # --------------------------------------------------

    def _load_access_token(self):

        token = os.getenv(
            "KITE_ACCESS_TOKEN", ""
        ).strip()

        if token:
            return token

        token_file = os.getenv(
            "KITE_TOKEN_FILE",
            "/var/data/kite_access_token.json"
        ).strip()

        if not token_file:
            return ""

        path = Path(token_file)

        if not path.is_file():
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
                return content

        except Exception as exc:
            print(
                "[KiteClient] Token file read error:",
                str(exc)
            )

            return ""

    # --------------------------------------------------
    # CLEAR CONNECTION
    # --------------------------------------------------

    def _clear_connection(self):

        self.kite = None
        self.access_token = ""
        self.is_connected = False
        self.profile = None

    # --------------------------------------------------
    # INITIALIZE CLIENT
    # --------------------------------------------------

    def _init_client(self):

        with self._lock:

            load_dotenv(
                ENV_FILE,
                override=False
            )

            self.api_key = os.getenv(
                "KITE_API_KEY", ""
            ).strip()

            self.api_secret = os.getenv(
                "KITE_API_SECRET", ""
            ).strip()

            token = self._load_access_token()

            if not self.api_key:
                self._clear_connection()

                print(
                    "[KiteClient] KITE_API_KEY missing."
                )

                return False

            if not token:
                self._clear_connection()

                print(
                    "[KiteClient] KITE_ACCESS_TOKEN missing."
                )

                return False

            return self.set_access_token(token)

    # --------------------------------------------------
    # SET TOKEN AFTER LOGIN
    # --------------------------------------------------

    def set_access_token(self, token):

        token = str(token or "").strip()

        with self._lock:

            if not token:
                self._clear_connection()
                return False

            self.api_key = os.getenv(
                "KITE_API_KEY", ""
            ).strip()

            self.api_secret = os.getenv(
                "KITE_API_SECRET", ""
            ).strip()

            if not self.api_key:
                self._clear_connection()

                print(
                    "[KiteClient] API key missing."
                )

                return False

            try:
                from kiteconnect import KiteConnect

                client = KiteConnect(
                    api_key=self.api_key,
                    timeout=12
                )

                client.set_access_token(token)

                # Verify the token with Zerodha.
                profile = client.profile()

                if (
                    not isinstance(profile, dict)
                    or not profile.get("user_id")
                ):
                    raise ValueError(
                        "Invalid Kite profile response."
                    )

                # Activate the client only after verification.
                self.kite = client
                self.access_token = token
                self.is_connected = True
                self.profile = profile

                # Make the new token available to other
                # services in this running backend process.
                os.environ["KITE_ACCESS_TOKEN"] = token

                print(
                    "[KiteClient] Connected as "
                    + str(profile.get("user_id"))
                )

                return True

            except Exception as exc:

                self._clear_connection()

                print(
                    "[KiteClient] Token verification failed:",
                    str(exc)
                )

                return False

    # --------------------------------------------------
    # GET CONNECTION STATUS
    # --------------------------------------------------

    def get_status(self):

        with self._lock:

            current_token = self._load_access_token()

            # Reinitialize if the token changed externally.
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
                ),
                "user_id": (
                    self.profile.get("user_id")
                    if self.profile
                    else None
                )
            }

    # --------------------------------------------------
    # RECONNECT
    # --------------------------------------------------

    def reconnect(self):

        return self._init_client()

    # --------------------------------------------------
    # LOGOUT
    # --------------------------------------------------

    def logout(self):

        with self._lock:

            self._clear_connection()

            os.environ.pop(
                "KITE_ACCESS_TOKEN",
                None
            )

            print(
                "[KiteClient] Local Kite session cleared."
            )

            return True


# ------------------------------------------------------
# SHARED APPLICATION INSTANCE
# ------------------------------------------------------

kite_manager = KiteClientManager()
