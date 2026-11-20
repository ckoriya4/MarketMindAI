
"""Kite OI snapshots with a fixed strike universe and persistent, observed history."""

import os
import sqlite3
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException, Query
from kiteconnect.exceptions import TokenException

from .market_session import session_bounds
from .kite_client import kite_manager

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


def kite_client():
    """
    Return the SAME authenticated Kite client used by the login manager.
    Never create a second client using an old .env access token.
    """
    with kite_manager._lock:
        if not kite_manager.is_connected or kite_manager.kite is None:
            raise HTTPException(
                503,
                "Kite login required. Authenticate using Login with Kite."
            )

        return kite_manager.kite


def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(DB)

    db.execute(
        "CREATE TABLE IF NOT EXISTS scopes "
        "(id TEXT PRIMARY KEY, config TEXT NOT NULL)"
    )

    db.execute(
        "CREATE TABLE IF NOT EXISTS samples "
        "(scope TEXT, time INTEGER, put_oi INTEGER, call_oi INTEGER, "
        "PRIMARY KEY(scope,time))"
    )

    return db


def provider_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if not isinstance(value, datetime):
        raise HTTPException(
            503,
            "Kite did not supply an option quote timestamp."
        )

    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)

    return int(value.timestamp())


def instruments(kite, today):
    global _instruments, _instrument_day

    if _instrument_day != today:
        _instruments = kite.instruments("NFO")
        _instrument_day = today

    return _instruments


def expiry_date(value):
    if isinstance(value, datetime):
        return value.date()

    return (
        value
        if isinstance(value, date)
        else date.fromisoformat(str(value))
    )


@router.get("/api/signals/oi")
def oi_signals(
    symbol: str = Query(
        "NIFTY",
        pattern="^(NIFTY|BANKNIFTY)$"
    ),
    expiry: str | None = Query(None),
    num_strikes: int = Query(7, ge=3, le=50),
    side_strikes: int = Query(4, ge=3, le=4),
    itm_strikes: int = Query(0, ge=0, le=1),
):
    from .session_recorder import recorder

    return recorder.read(
        symbol,
        expiry,
        side_strikes,
        itm_strikes
    )


def live_expiries():
    """Actual first four NIFTY expiries from Kite."""

    with lock:
        try:
            today = datetime.now(IST).date()
            kite = kite_client()

            values = sorted({
                expiry_date(i["expiry"])
                for i in instruments(kite, today)
                if (
                    i.get("name") == "NIFTY"
                    and i.get("instrument_type") in ("CE", "PE")
                    and expiry_date(i["expiry"]) >= today
                )
            })

            if not values:
                raise HTTPException(
                    503,
                    "No current NIFTY option expiries found in Kite."
                )

            return [
                d.strftime("%d-%b-%Y").upper()
                for d in values[:4]
            ]

        except HTTPException:
            raise

        except TokenException:
            raise HTTPException(
                401,
                "Kite session expired."
            ) from None

        except Exception:
            raise HTTPException(
                503,
                "Cannot load option expiries from Kite."
            ) from None


@router.get("/api/signals/collector/status")
def collector_status():
    from .session_recorder import recorder

    return recorder.status()
