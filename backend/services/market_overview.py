
"""Live market-strip snapshots; observed mini-chart values only."""

import math
import time

from collections import deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, HTTPException
from kiteconnect.exceptions import TokenException

from .oi_signal import IST, kite_client, provider_time
from .energy_service import mcx_quote


router = APIRouter()

_lock = Lock()
_cache = None
_cache_at = 0.0
_history = {}


# ---------------------------------------------------------
# LIVE INDEX INSTRUMENTS
# ---------------------------------------------------------
# These are Zerodha Kite exchange:tradingsymbol keys.
# CRUDE is fetched separately through the existing MCX service.

INDEX_KEYS = {
    "NIFTY": ("NIFTY 50", "NSE:NIFTY 50"),
    "BANKNIFTY": ("BANK NIFTY", "NSE:NIFTY BANK"),
    "FINNIFTY": ("FINNIFTY", "NSE:NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("MIDCPNIFTY", "NSE:NIFTY MID SELECT"),
    "NIFTYNXT50": ("NIFTY NEXT 50", "NSE:NIFTY NEXT 50"),
    "SENSEX": ("SENSEX", "BSE:SENSEX"),
    "BANKEX": ("BANKEX", "BSE:BANKEX"),
}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def change_values(price, previous):

    if not finite(previous) or previous <= 0:
        return None, None

    change = price - previous

    return (
        round(change, 2),
        round(change / previous * 100, 2)
    )


def atm_strike(price, step=50):

    return int(
        math.floor(price / step + 0.5) * step
    )


# ---------------------------------------------------------
# MINI CHART HISTORY
# ---------------------------------------------------------

def observations(key, value, observed):

    day = datetime.fromtimestamp(
        observed,
        IST
    ).date().isoformat()

    old = _history.get(key)

    if old is None or old["day"] != day:

        old = {
            "day": day,
            "points": deque(maxlen=120)
        }

        _history[key] = old

    points = old["points"]

    if not points or observed > points[-1]["time"]:

        points.append({
            "time": observed,
            "value": value
        })

    elif observed == points[-1]["time"]:

        points[-1] = {
            "time": observed,
            "value": value
        }

    return list(points)


# ---------------------------------------------------------
# INDEX CARD
# ---------------------------------------------------------

def index_card(code, name, quote, received):

    quote = quote or {}

    price = quote.get("last_price")

    if not finite(price) or price <= 0:

        return {
            "id": code,
            "symbol": code,
            "name": name,
            "status": "unavailable",
            "price": None,
            "change": None,
            "change_pct": None,
            "currency": "INR",
            "source": "Kite",
            "history": [],
            "error": (
                "Live quote unavailable. Check the Kite "
                "instrument key and exchange market-data permissions."
            )
        }

    supplied = quote.get("timestamp")

    try:

        ts = (
            provider_time(supplied)
            if supplied is not None
            else None
        )

    except (ValueError, TypeError, HTTPException):

        ts = None

    observed = ts if ts is not None else received

    status = (
        "stale"
        if ts is not None and not -5 <= received - ts <= 90
        else "ok"
    )

    ohlc = quote.get("ohlc") or {}

    change, pct = change_values(
        price,
        ohlc.get("close")
    )

    return {
        "id": code,
        "symbol": code,
        "name": name,
        "price": price,
        "change": change,
        "change_pct": pct,
        "currency": "INR",
        "status": status,
        "source": "Kite",
        "quote_time": ts,
        "received_at": received,
        "time_kind": (
            "exchange" if ts is not None else "received"
        ),
        "history": observations(
            code,
            price,
            observed
        )
    }


# ---------------------------------------------------------
# CRUDE OIL CARD
# ---------------------------------------------------------

def crude_card(received):

    try:

        crude = mcx_quote() or {}

    except Exception as exc:

        print(
            "[MarketOverview] Crude quote error:",
            str(exc)
        )

        crude = {
            "price": None,
            "error": "MCX crude oil quote request failed."
        }

    price = crude.get("price")

    if not finite(price) or price <= 0:

        return {
            "id": "CRUDE",
            "symbol": "CRUDE",
            "name": "CRUDE OIL",
            "price": None,
            "change": None,
            "change_pct": None,
            "currency": "INR",
            "status": "unavailable",
            "source": "Kite / MCX",
            "history": [],
            "error": crude.get(
                "error",
                "MCX crude oil quote unavailable."
            )
        }

    ts = crude.get("quote_time")

    status = (
        "ok"
        if (
            crude.get("status") == "fresh"
            and ts is not None
            and -5 <= received - ts <= 90
        )
        else "stale"
    )

    return {
        "id": "CRUDE",
        "symbol": crude.get("symbol", "CRUDE"),
        "name": "CRUDE OIL",
        "price": price,
        "change": crude.get("change"),
        "change_pct": crude.get("change_pct"),
        "currency": "INR",
        "status": status,
        "source": "Kite / MCX",
        "expiry": crude.get("expiry"),
        "quote_time": ts,
        "received_at": received,
        "time_kind": "exchange",
        "history": observations(
            "CRUDE:" + str(crude.get("symbol")),
            price,
            ts if ts is not None else received
        )
    }


# ---------------------------------------------------------
# MARKET OVERVIEW API
# ---------------------------------------------------------

@router.get("/api/market/overview")
def market_overview():

    global _cache, _cache_at

    with _lock:

        # Reuse snapshot for five seconds.
        if (
            _cache is not None
            and time.monotonic() - _cache_at < 5
        ):

            return _cache

        # -------------------------------------------------
        # FETCH ALL INDEX QUOTES FROM KITE
        # -------------------------------------------------

        try:

            kite = kite_client()

            instrument_keys = [
                instrument
                for name, instrument in INDEX_KEYS.values()
            ]

            raw = kite.quote(instrument_keys)

            if not isinstance(raw, dict):
                raw = {}

        except TokenException:

            raise HTTPException(
                401,
                "Kite session expired. Update the backend "
                "access token and restart."
            ) from None

        except HTTPException:

            raise

        except Exception as exc:

            print(
                "[MarketOverview] Kite quote error:",
                str(exc)
            )

            raise HTTPException(
                503,
                "Market quotes unavailable. Check Kite "
                "connectivity and NSE/BSE quote permissions."
            ) from None

        received = int(time.time())

        # -------------------------------------------------
        # BUILD ALL SEVEN INDEX CARDS
        # -------------------------------------------------

        cards = []

        for code, (name, instrument_key) in INDEX_KEYS.items():

            quote = raw.get(instrument_key, {})

            card = index_card(
                code,
                name,
                quote,
                received
            )

            cards.append(card)

        # -------------------------------------------------
        # ADD LIVE MCX CRUDE OIL
        # -------------------------------------------------

        cards.append(
            crude_card(received)
        )

        # -------------------------------------------------
        # ATM DATA BASED ON LIVE NIFTY
        # -------------------------------------------------

        nifty = next(
            card
            for card in cards
            if card["id"] == "NIFTY"
        )

        spot = nifty.get("price")

        atm = {
            "strike": (
                atm_strike(spot)
                if finite(spot) and spot > 0
                else None
            ),
            "spot": spot,
            "step": 50,
            "spot_change_pct": nifty.get("change_pct"),
            "status": nifty["status"],
            "quote_time": nifty.get("quote_time")
        }

        # -------------------------------------------------
        # FINAL RESPONSE
        # -------------------------------------------------

        _cache = {
            "source": "kite",
            "cards": cards,
            "atm": atm,
            "fetched_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "ok"
                if all(
                    card["status"] == "ok"
                    for card in cards
                )
                else "partial"
            )
        }

        _cache_at = time.monotonic()

        return _cache
