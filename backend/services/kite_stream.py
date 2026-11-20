
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
                    access_token,
                    reconnect=True
                )

                self.ticker = ticker
                self.connected = False

                # Clear old ticks but preserve subscriptions.
                self.latest_ticks.clear()

            except Exception as exc:

                self.ticker = None
                self.connected = False

                print(
                    "[KiteStream] Initialization error:",
                    str(exc)
                )

                return False

        # Register callbacks.
        ticker.on_connect = self._on_connect
        ticker.on_ticks = self._on_ticks
        ticker.on_close = self._on_close
        ticker.on_error = self._on_error

        try:

            ticker.connect(threaded=True)

            print("[KiteStream] WebSocket start requested")

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
    # CHECK CURRENT CONNECTION
    # --------------------------------------------------

    def _is_current(self, ws):

        with self.lock:
            return self.ticker is ws

    # --------------------------------------------------
    # ON CONNECT
    # --------------------------------------------------

    def _on_connect(self, ws, response):

        with self.lock:

            # Ignore callbacks from an old connection.
            if self.ticker is not ws:
                return

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

            if self.ticker is not ws:
                return

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

            # Do not let an old connection update new status.
            if self.ticker is not ws:
                return

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

        with self.lock:

            if self.ticker is not ws:
                return

            self.connected = False

        print(
            "[KiteStream] Error:",
            code,
            reason
        )

    # --------------------------------------------------
    # SUBSCRIBE INSTRUMENT
    # --------------------------------------------------

    def subscribe(self, token):

        try:
            token = int(token)
        except (TypeError, ValueError):
            print("[KiteStream] Invalid instrument token:", token)
            return False

        if token <= 0:
            return False

        with self.lock:

            # Save token even if WebSocket is not connected yet.
            self.subscribed_tokens.add(token)

            ticker = self.ticker
            connected = self.connected

        if not ticker or not connected:
            return True

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

            return True

        except Exception as exc:

            print(
                "[KiteStream] Subscribe error:",
                str(exc)
            )

            return False

    # --------------------------------------------------
    # UNSUBSCRIBE INSTRUMENT
    # --------------------------------------------------

    def unsubscribe(self, token):

        try:
            token = int(token)
        except (TypeError, ValueError):
            return False

        with self.lock:

            self.subscribed_tokens.discard(token)
            self.latest_ticks.pop(token, None)

            ticker = self.ticker
            connected = self.connected

        if ticker and connected:

            try:

                ticker.unsubscribe([token])

                print(
                    "[KiteStream] Unsubscribed:",
                    token
                )

            except Exception as exc:

                print(
                    "[KiteStream] Unsubscribe error:",
                    str(exc)
                )

                return False

        return True

    # --------------------------------------------------
    # GET LATEST TICK
    # --------------------------------------------------

    def get_tick(self, token):

        try:
            token = int(token)
        except (TypeError, ValueError):

            return {
                "status": "error",
                "detail": "Invalid instrument token"
            }

        with self.lock:

            tick = self.latest_ticks.get(token)
            connected = self.connected

            if tick is None:

                return {
                    "status": "waiting",
                    "websocket_connected": connected,
                    "instrument_token": token
                }

            timestamp = tick.get(
                "exchange_timestamp"
            )

            if hasattr(timestamp, "isoformat"):
                timestamp = timestamp.isoformat()
            elif timestamp is not None:
                timestamp = str(timestamp)

            return {
                "status": "success",
                "websocket_connected": connected,
                "instrument_token": token,
                "last_price": tick.get("last_price"),
                "last_quantity": tick.get("last_quantity"),
                "volume": tick.get("volume_traded"),
                "average_price": tick.get("average_price"),
                "oi": tick.get("oi"),
                "exchange_timestamp": timestamp
            }

    # --------------------------------------------------
    # STREAM STATUS
    # --------------------------------------------------

    def get_status(self):

        with self.lock:

            return {
                "started": self.ticker is not None,
                "connected": self.connected,
                "subscribed_count": len(
                    self.subscribed_tokens
                ),
                "tick_count": len(
                    self.latest_ticks
                )
            }

    # --------------------------------------------------
    # STOP WEBSOCKET
    # --------------------------------------------------

    def stop(self):

        with self.lock:

            ticker = self.ticker

            # Detach old connection before closing it.
            self.ticker = None
            self.connected = False

            # Preserve subscribed_tokens for next connection.
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

        return True


# ------------------------------------------------------
# SHARED WEBSOCKET INSTANCE
# ------------------------------------------------------

kite_stream = KiteStream()
