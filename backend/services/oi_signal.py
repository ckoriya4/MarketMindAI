
"""Kite OI snapshots with a fixed strike universe and persistent observed history."""

import sqlite3
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException, Query
from kiteconnect.exceptions import TokenException

from .market_session import session_bounds
from .kite_client import kite_manager


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

BASE = Path(__file__).resolve().parents[1]

IST = timezone(timedelta(hours=5, minutes=30))

DB = BASE / "data" / "oi-signals.sqlite3"

router = APIRouter()

lock = Lock()

_instruments = []
_instrument_day = None

_cache = {}


INDEX = {
    "NIFTY": ("NSE:NIFTY 50", 50),
    "BANKNIFTY": ("NSE:NIFTY BANK", 100),
}


# ---------------------------------------------------------
# SHARED KITE CLIENT
# ---------------------------------------------------------

def kite_client():
    """
    Return the SAME authenticated Kite client used by
    KiteClientManager.

    Never create a second Kite client or use an old
    access token from an environment variable.
    """

    with kite_manager._lock:

        if (
            not kite_manager.is_connected
            or kite_manager.kite is None
        ):

            raise HTTPException(
                status_code=503,
                detail=(
                    "Kite login required. "
                    "Authenticate using Login with Kite."
                )
            )

        return kite_manager.kite


# ---------------------------------------------------------
# SQLITE STORAGE
# ---------------------------------------------------------

def connection():

    DB.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    db = sqlite3.connect(
        DB,
        timeout=15
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scopes (
            id TEXT PRIMARY KEY,
            config TEXT NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS samples (
            scope TEXT,
            time INTEGER,
            put_oi INTEGER,
            call_oi INTEGER,
            PRIMARY KEY(scope, time)
        )
        """
    )

    return db


# ---------------------------------------------------------
# KITE TIMESTAMP
# ---------------------------------------------------------

def provider_time(value):

    if isinstance(value, str):

        value = datetime.fromisoformat(value)

    if not isinstance(value, datetime):

        raise HTTPException(
            status_code=503,
            detail=(
                "Kite did not supply an option quote timestamp."
            )
        )

    if value.tzinfo is None:

        value = value.replace(tzinfo=IST)

    return int(value.timestamp())


# ---------------------------------------------------------
# INSTRUMENT CACHE
# ---------------------------------------------------------

def instruments(kite, today):

    global _instruments
    global _instrument_day

    if _instrument_day != today:

        _instruments = kite.instruments("NFO")

        _instrument_day = today

    return _instruments


# ---------------------------------------------------------
# EXPIRY CONVERSION
# ---------------------------------------------------------

def expiry_date(value):

    if isinstance(value, datetime):

        return value.date()

    return (
        value
        if isinstance(value, date)
        else date.fromisoformat(str(value))
    )


# ---------------------------------------------------------
# OI SIGNAL API
# ---------------------------------------------------------

@router.get("/api/signals/oi")
def oi_signals(

    symbol: str = Query(
        "NIFTY",
        pattern="^(NIFTY|BANKNIFTY)$"
    ),

    expiry: str | None = Query(None),

    num_strikes: int = Query(
        7,
        ge=3,
        le=50
    ),

    side_strikes: int = Query(
        4,
        ge=3,
        le=4
    ),

    itm_strikes: int = Query(
        0,
        ge=0,
        le=1
    ),

):

    from .session_recorder import recorder

    return recorder.read(
        symbol,
        expiry,
        side_strikes,
        itm_strikes
    )


# ---------------------------------------------------------
# LIVE OPTION EXPIRIES
# ---------------------------------------------------------

def live_expiries():
    """
    Return the first four actual upcoming NIFTY expiries
    from Zerodha Kite instruments.
    """

    with lock:

        try:

            today = datetime.now(IST).date()

            kite = kite_client()

            values = sorted({

                expiry_date(instrument["expiry"])

                for instrument in instruments(
                    kite,
                    today
                )

                if (
                    instrument.get("name") == "NIFTY"

                    and instrument.get(
                        "instrument_type"
                    ) in ("CE", "PE")

                    and expiry_date(
                        instrument["expiry"]
                    ) >= today
                )

            })

            if not values:

                raise HTTPException(
                    status_code=503,
                    detail=(
                        "No current NIFTY option expiries "
                        "found in Kite."
                    )
                )

            return [
                expiry.strftime("%d-%b-%Y").upper()
                for expiry in values[:4]
            ]

        except HTTPException:

            raise

        except TokenException:

            raise HTTPException(
                status_code=401,
                detail="Kite session expired."
            ) from None

        except Exception:

            raise HTTPException(
                status_code=503,
                detail=(
                    "Cannot load option expiries from Kite."
                )
            ) from None


# ---------------------------------------------------------
# COLLECTOR STATUS
# ---------------------------------------------------------

@router.get("/api/signals/collector/status")
def collector_status():

    from .session_recorder import recorder

    return recorder.status()


# ---------------------------------------------------------
# END
# ---------------------------------------------------------
