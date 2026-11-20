
# backend/services/kite_stream.py

from threading import RLock
from kiteconnect import KiteTicker


class KiteStream:

    def __init__(self):
        self.ticker = None
        self.connected = False

        self.subscribed_tokens = set()
        self.latest_ticks = {}

        self.lock = RLock()

    # --------------------------------------------------
    # START WEBSOCKET
    # --------------------------------------------------

    def start(self, api_key, access_token):

        if not api_key or not access_token:
            print("[KiteStream] Missing Kite credentials")
            return False

        with self.lock:

            # Avoid duplicate WebSocket connections.
            if self.ticker is not None:
                print("[KiteStream] WebSocket already started")
                return False

            try:
                ticker = KiteTicker(
                    api_key,
                    access_token
                )

                self.ticker = ticker
                self.connected = False

                # Clear old ticks, but preserve subscriptions.
                self.latest_ticks.clear()

            except Exception as exc:

                self.ticker = None

                print(
                    "[KiteStream] Initialization error:",
                    str(exc)
                )

                return False

        ticker.on_connect = self._on_connect
        ticker.on_ticks = self._on_ticks
        ticker.on_close = self._on_close
        ticker.on_error = self._on_error

        try:

            ticker.connect(threaded=True)

            print("[KiteStream] WebSocket starting")

            return True

        except Exception as exc:

            with self.lock:
                if self.ticker is ticker:
                    self.ticker = None

                self.connected = False

            print(
                "[KiteStream] Start error:",
                str(exc)
            )

            return False

    # --------------------------------------------------
    # ON CONNECT
    # --------------------------------------------------

    def _on_connect(self, ws, response):

        with self.lock:

            self.connected = True

            tokens = list(
                self.subscribed_tokens
            )

        if tokens:

            try:
                ws.subscribe(tokens)

                ws.set_mode(
                    ws.MODE_FULL,
                    tokens
                )

                print(
                    "[KiteStream] Resubscribed tokens:",
                    len(tokens)
                )

            except Exception as exc:

                print(
                    "[KiteStream] Subscription error:",
                    str(exc)
                )

        print("[KiteStream] Connected")

    # --------------------------------------------------
    # ON TICKS
    # --------------------------------------------------

    def _on_ticks(self, ws, ticks):

        with self.lock:

            for tick in ticks:

                token = tick.get(
                    "instrument_token"
                )

                if token is not None:

                    self.latest_ticks[int(token)] = dict(
                        tick
                    )

    # --------------------------------------------------
    # ON CLOSE
    # --------------------------------------------------

    def _on_close(self, ws, code, reason):

        with self.lock:

            self.connected = False

        print(
            "[KiteStream] Closed:",
            code,
            reason
        )

    # --------------------------------------------------
    # ON ERROR
    # --------------------------------------------------

    def _on_error(self, ws, code, reason):

        print(
            "[KiteStream] Error:",
            code,
            reason
        )

    # --------------------------------------------------
    # SUBSCRIBE INSTRUMENT
    # --------------------------------------------------

    def subscribe(self, token):

        token = int(token)

        with self.lock:

            if token in self.subscribed_tokens:
                return

            self.subscribed_tokens.add(token)

            ticker = self.ticker
            connected = self.connected

        if ticker and connected:

            try:

                ticker.subscribe([token])

                ticker.set_mode(
                    ticker.MODE_FULL,
                    [token]
                )

                print(
                    "[KiteStream] Subscribed:",
                    token
                )

            except Exception as exc:

                print(
                    "[KiteStream] Subscribe error:",
                    str(exc)
                )

    # --------------------------------------------------
    # GET LATEST TICK
    # --------------------------------------------------

    def get_tick(self, token):

        token = int(token)

        with self.lock:

            tick = self.latest_ticks.get(token)

            connected = self.connected

            if tick is None:

                return {
                    "status": "waiting",
                    "websocket_connected": connected
                }

            timestamp = tick.get(
                "exchange_timestamp"
            )

            return {
                "status": "success",
                "websocket_connected": connected,
                "instrument_token": token,
                "last_price": tick.get("last_price"),
                "last_quantity": tick.get("last_quantity"),
                "volume": tick.get("volume_traded"),
                "average_price": tick.get("average_price"),
                "oi": tick.get("oi"),
                "exchange_timestamp": (
                    timestamp.isoformat()
                    if timestamp
                    else None
                )
            }

    # --------------------------------------------------
    # STOP WEBSOCKET
    # --------------------------------------------------

    def stop(self):

        with self.lock:

            ticker = self.ticker

            self.ticker = None
            self.connected = False

            # Preserve subscribed_tokens.
            # They will be restored on the next connection.
            self.latest_ticks.clear()

        if ticker:

            try:

                ticker.close()

                print(
                    "[KiteStream] WebSocket stopped"
                )

            except Exception as exc:

                print(
                    "[KiteStream] Close error:",
                    str(exc)
                )


# ------------------------------------------------------
# SHARED WEBSOCKET INSTANCE
# ------------------------------------------------------

kite_stream = KiteStream()
