
# backend/services/kite_stream.py

from threading import Lock
from kiteconnect import KiteTicker


class KiteStream:
    def __init__(self):
        self.ticker = None
        self.connected = False
        self.subscribed_tokens = set()
        self.latest_ticks = {}
        self.lock = Lock()

    def start(self, api_key, access_token):
        if not api_key or not access_token:
            print("[KiteStream] Missing Kite credentials")
            return

        with self.lock:
            if self.ticker is not None:
                return

            self.ticker = KiteTicker(api_key, access_token)
            ticker = self.ticker

        ticker.on_connect = self._on_connect
        ticker.on_ticks = self._on_ticks
        ticker.on_close = self._on_close
        ticker.on_error = self._on_error

        ticker.connect(threaded=True)

        print("[KiteStream] WebSocket starting")

    def _on_connect(self, ws, response):
        with self.lock:
            self.connected = True
            tokens = list(self.subscribed_tokens)

        if tokens:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)

        print("[KiteStream] Connected")

    def _on_ticks(self, ws, ticks):
        with self.lock:
            for tick in ticks:
                token = tick.get("instrument_token")
                if token is not None:
                    self.latest_ticks[token] = dict(tick)

    def _on_close(self, ws, code, reason):
        with self.lock:
            self.connected = False

        print("[KiteStream] Closed:", code, reason)

    def _on_error(self, ws, code, reason):
        print("[KiteStream] Error:", code, reason)

    def subscribe(self, token):
        token = int(token)

        with self.lock:
            if token in self.subscribed_tokens:
                return

            self.subscribed_tokens.add(token)
            ticker = self.ticker
            connected = self.connected

        if ticker and connected:
            ticker.subscribe([token])
            ticker.set_mode(ticker.MODE_FULL, [token])

    def get_tick(self, token):
        with self.lock:
            tick = self.latest_ticks.get(int(token))
            connected = self.connected

            if tick is None:
                return {
                    "status": "waiting",
                    "websocket_connected": connected
                }

            # Return JSON-safe values only.
            timestamp = tick.get("exchange_timestamp")

            return {
                "status": "success",
                "websocket_connected": connected,
                "instrument_token": int(token),
                "last_price": tick.get("last_price"),
                "last_quantity": tick.get("last_quantity"),
                "volume": tick.get("volume_traded"),
                "average_price": tick.get("average_price"),
                "oi": tick.get("oi"),
                "exchange_timestamp": (
                    timestamp.isoformat()
                    if timestamp else None
                )
            }

    def stop(self):
        with self.lock:
            ticker = self.ticker
            self.ticker = None
            self.connected = False
            self.subscribed_tokens.clear()
            self.latest_ticks.clear()

        if ticker:
            try:
                ticker.close()
            except Exception as exc:
                print("[KiteStream] Close error:", exc)


kite_stream = KiteStream()
